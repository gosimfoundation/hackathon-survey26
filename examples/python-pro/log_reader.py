"""Optional model stage: read the free-text notes that come with observation requests.

Some task cards attach a longer `reason` text to observation requests: notes from the observatory staff. They
can mention things that matter for the survey (closures, weather, instrument trouble, instructions). This
module sends every new note once to the configured model, together with a few earlier notes as context and
the current time, and asks for a small JSON summary of operational facts with times. agent.py turns the
answer into actions with three plain rules:

    closures   -> wait while the whole site is announced closed
    avoid      -> down-weight the named compass sectors during the announced window
    report_at  -> send a `report` once the staff say the instrument itself has a problem (now or from an
                  announced time), or when they explicitly ask for a problem report at a time

Calls run on background threads (the decision loop never needs the answer to continue), are cached per
message, retried with backoff on HTTP 429 / 5xx, and simply skipped without a key or after errors. Short
labels such as "time-critical follow-up" are not notes and are never sent.
"""
from __future__ import annotations

import random
import threading
import time
import urllib.error
from datetime import datetime, timedelta, timezone

DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
MIN_NOTE_CHARS = 31          # shorter reasons are labels, not notes
CONTEXT_NOTES = 4            # earlier notes sent along as context
CONTEXT_CHARS = 6000
CALL_DEADLINE = 360.0        # give up on one note after this many seconds (retries included)

SYSTEM = (
    "You help run a robotic survey telescope. You get one new note from the observatory staff (shift log, chat "
    "or a relayed message), a few earlier notes as context, the current time and the site's offset from UTC. "
    "Extract only operational facts that matter for observing, each with its time window. Read carefully: "
    "the notes may be informal, mix languages, and contain corrections; a later statement replaces an earlier "
    "one about the same thing. Ignore hearsay, jokes and anything about other sites. Leave a list empty when unsure.\n"
    "Convert every time to UTC and write it as YYYY-MM-DDTHH:MM. Lists:\n"
    "closures: windows in which the whole telescope will not observe (dome closed, maintenance, shutdown, "
    "closed for weather).\n"
    "avoid: windows in which named parts of the sky (compass sectors N NE E SE S SW W NW, or ALL) cannot be "
    "observed usefully (thick cloud, rain, wind, other activity). Not for conditions the note calls fine.\n"
    "report_at: moments from which the staff say the telescope's own instrument is degraded or misbehaving "
    "(already happening, or announced for a future time), or at which they explicitly ask for an instrument "
    "problem report. Not weather, and not earthquakes (a report does not repair those). Only facts stated in "
    "the NEW note.\n"
    'Reply with one JSON object only: {"closures": [{"start_utc": "...", "end_utc": "..."}], '
    '"avoid": [{"start_utc": "...", "end_utc": "...", "directions": ["SW", ...]}], '
    '"report_at": [{"utc": "...", "why": "<10 words"}], "summary": "<20 words"}'
)


def _utc(text) -> datetime | None:
    try:
        return datetime.strptime(str(text).strip()[:16].replace(" ", "T"), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class LogReader:
    def __init__(self, client, utc_offset_hours: float, log=lambda text: None, workers: int = 2):
        self.client = client
        self.offset = timedelta(hours=utc_offset_hours)
        self.log = log
        self.seen: set = set()                 # request ids already sent (cache per note)
        self.notes: list = []                  # earlier note texts (context)
        self.answers: list = []                # (request id, issued, answer) not yet applied
        self.pending = 0
        self.lock = threading.Lock()
        self.slots = threading.Semaphore(workers)
        self.done_event = threading.Event()
        # the facts so far
        self.closures: list = []               # [(start, end)]
        self.avoid: list = []                  # [(start, end, set of directions)]
        self.report_times: list = []           # [datetime] not yet acted on

    # --- input ---------------------------------------------------------------------------------------

    def feed(self, requests: list, now: datetime, wallclock_left: float) -> int:
        """Start reading every note not seen before; returns how many were started."""
        started = 0
        for request in requests:
            rid = request.get("request_id")
            text = str(request.get("reason") or "").strip()
            if rid in self.seen or len(text) < MIN_NOTE_CHARS:
                continue
            self.seen.add(rid)
            context = []
            for note in reversed(self.notes[-CONTEXT_NOTES:]):
                if sum(len(c) for c in context) + len(note) > CONTEXT_CHARS:
                    break
                context.insert(0, note)
            self.notes.append(text)
            issued = _utc(request.get("issued_at_utc", "")) or now
            local = now + self.offset
            user = {"now_utc": now.strftime("%Y-%m-%dT%H:%M"), "now_local": local.strftime("%Y-%m-%dT%H:%M (%A)"),
                    "site_utc_offset_hours": self.offset.total_seconds() / 3600.0,
                    "note_issued_utc": issued.strftime("%Y-%m-%dT%H:%M"),
                    "earlier_notes": context, "new_note": text}
            deadline = min(CALL_DEADLINE, wallclock_left - 60.0)
            if deadline < 10.0:
                continue
            with self.lock:
                self.pending += 1
                self.done_event.clear()
            threading.Thread(target=self._run, args=(rid, issued, user, deadline), daemon=True).start()
            started += 1
        return started

    def _run(self, rid, issued, user, deadline) -> None:
        started = time.monotonic()
        answer = None
        delay = 5.0
        with self.slots:
            while time.monotonic() - started < deadline:
                try:
                    answer = self.client._request(SYSTEM, user, min(240.0, deadline - (time.monotonic() - started)),
                                                  max_tokens=12000)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code != 429 and exc.code < 500:
                        break                          # auth / quota / bad request: retrying will not help
                except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
                    pass
                time.sleep(min(delay * (0.75 + 0.5 * random.random()), max(0.0, deadline - (time.monotonic() - started))))
                delay = min(delay * 2, 60.0)
        with self.lock:
            if isinstance(answer, dict):
                self.answers.append((rid, issued, answer))
            else:
                self.log(f"log reader: no answer for request {rid}; rules decide")
            self.pending -= 1
            if self.pending == 0:
                self.done_event.set()

    def wait(self, seconds: float) -> None:
        """Wait (free of CPU) up to `seconds` for notes still being read."""
        if self.pending and seconds > 0:
            self.done_event.wait(seconds)

    # --- answers -> facts ----------------------------------------------------------------------------

    def collect(self) -> None:
        with self.lock:
            answers, self.answers = self.answers, []
        for rid, issued, answer in answers:
            self._apply(rid, issued, answer)

    def _apply(self, rid, issued, answer) -> None:
        def items(key):
            value = answer.get(key)
            return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []

        for c in items("closures"):
            start, end = _utc(c.get("start_utc")), _utc(c.get("end_utc"))
            if start and end and end > start and end - start <= timedelta(days=10):
                self.closures.append((start, end))
        for a in items("avoid"):
            start, end = _utc(a.get("start_utc")), _utc(a.get("end_utc"))
            dirs = a.get("directions") if isinstance(a.get("directions"), list) else []
            dirs = set(DIRECTIONS) if "ALL" in dirs else {d for d in dirs if d in DIRECTIONS}
            if start and end and end > start and dirs:
                self.avoid.append((start, end, dirs))
        for r in items("report_at"):
            t = _utc(r.get("utc"))
            # stated now or announced for later; ignore stale or far-off times, and duplicates
            if t and issued - timedelta(hours=24) <= t <= issued + timedelta(days=60) \
                    and all(abs((t - x).total_seconds()) > 3600 for x in self.report_times):
                self.report_times.append(t)
        self.log(f"log reader {rid}: {str(answer.get('summary', ''))[:100]} | closures {len(items('closures'))} "
                 f"avoid {len(items('avoid'))} report_at {[str(r.get('utc')) for r in items('report_at')]}")

    def closed(self, now: datetime):
        """End of the announced closure covering `now`, or None."""
        ends = [end for start, end in self.closures if start <= now < end]
        return max(ends) if ends else None

    def avoid_now(self, now: datetime) -> set:
        out: set = set()
        for start, end, dirs in self.avoid:
            if start <= now < end:
                out |= dirs
        return out

    def report_due(self, now: datetime):
        """The earliest announced problem time that has arrived (and is recent), removed from the list."""
        due = sorted(t for t in self.report_times if t <= now)
        for t in due:
            self.report_times.remove(t)
        recent = [t for t in due if now - t <= timedelta(hours=24)]
        return recent[0] if recent else None
