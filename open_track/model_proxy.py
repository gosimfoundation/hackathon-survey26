"""Metered model proxy for one open-track run (runs in its own container; standard library only).

The agent container has no network except an internal one shared with this proxy, so every
aohkit.llm.ask call ends here. The proxy forwards to the participant's own OpenAI-compatible API
(base URL, model and key from the environment; the key never enters the agent container), caps the
number of calls and writes one ledger line per successful call. The ledger is the usage the engine
charges against the score, so the agent can neither skip nor edit it.

Env: OPEN_MODEL_BASE, OPEN_MODEL_NAME, OPEN_MODEL_KEY ('' = no model: every call is refused, nothing
is metered), OPEN_LEDGER (path), OPEN_MAX_CALLS (default 200), OPEN_PORT (default 8080).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.environ.get("OPEN_MODEL_BASE", "").rstrip("/")
MODEL = os.environ.get("OPEN_MODEL_NAME", "")
KEY = os.environ.get("OPEN_MODEL_KEY", "")
LEDGER = os.environ.get("OPEN_LEDGER", "/ledger/ledger.jsonl")
MAX_CALLS = int(os.environ.get("OPEN_MAX_CALLS", "200"))
MAX_BODY = 1_000_000
_lock = threading.Lock()
_state = {"calls": 0}


def _upstream(body: dict) -> dict:
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    last: Exception | None = None
    for attempt in range(4):  # transient failures are retried; only a success is metered
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code < 500 and exc.code != 429:
                break
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:  # refuse whole: never leave a partial body on the connection
            self.close_connection = True
            self.send_response(413)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        raw = self.rfile.read(length)
        try:
            if not KEY:
                raise RuntimeError("no model API configured for this submission")
            req = json.loads(raw)
            with _lock:
                if _state["calls"] >= MAX_CALLS:
                    raise RuntimeError(f"LLM call cap ({MAX_CALLS}) reached")
                _state["calls"] += 1
            body = {"model": MODEL, "max_tokens": max(1, min(int(req.get("max_tokens", 400)), 1500)),
                    "messages": [{"role": "system", "content": str(req.get("system", ""))[:20000]},
                                 {"role": "user", "content": str(req.get("prompt", ""))[:60000]}]}
            t0 = time.time()
            out = _upstream(body)
            usage = out.get("usage") or {}
            text = out["choices"][0]["message"]["content"] or ""
            # never charge less than a rough size estimate (4 characters per token), whatever the API reports
            est_in = sum(len(m["content"]) for m in body["messages"]) // 4
            est_out = len(text) // 4
            with _lock, open(LEDGER, "a") as f:
                f.write(json.dumps({"t": round(time.time() - t0, 2), "in": max(int(usage.get("prompt_tokens", 0) or 0), est_in),
                                    "out": max(int(usage.get("completion_tokens", 0) or 0), est_out)}) + "\n")
            payload = {"text": text}
        except Exception as exc:  # noqa: BLE001 - report to the agent, never crash
            payload = {"error": f"{type(exc).__name__}: {str(exc)[:300]}".replace(KEY, "***") if KEY else f"{type(exc).__name__}: {str(exc)[:300]}"}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # readiness probe
        data = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    open(LEDGER, "a").close()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("OPEN_PORT", "8080"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
