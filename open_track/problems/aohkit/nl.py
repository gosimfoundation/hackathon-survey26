"""Natural-language intel layer (v-next problems).

The environment decides WHAT a message says (a kind + typed slot values, all truth-consistent); this module
decides HOW it is written: a template drawn from a pool of human-like messages (many authors, styles and
languages, pre-generated offline), with every slot value formatted in a randomly chosen style for that
template's language (digits / words / relative times / other time zones / sexagesimal coordinates ...).

Two pools per problem:
  <problem>/nl_pool_dev.json      public, used for dev seeds (< HIDDEN_SEED_MIN)
  _hidden/nl/<problem>.json       organizer-only, different authors and wording, used for hidden seeds
so a parser fitted to the public messages does not transfer; reading the meaning does.
The environment never calls an LLM at run time: rendering is deterministic given the seed.
"""
from __future__ import annotations

import json, os, random, string

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HIDDEN_SEED_MIN = 10 ** 6
LANG_WEIGHTS = {"en": 0.58, "zh": 0.2, "ja": 0.11, "es": 0.11}

# ------------------------------------------------------------------ number words
_EN = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_EN_T = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ES = "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis diecisiete dieciocho diecinueve veinte".split()
_ZH = "零一二三四五六七八九"


def en_words(n):
    n = int(n)
    if n < 20:
        return _EN[n]
    if n < 100:
        return _EN_T[n // 10] + ("" if n % 10 == 0 else "-" + _EN[n % 10])
    return str(n)


def zh_num(n):
    n = int(n)
    if n < 10:
        return _ZH[n]
    if n < 20:
        return "十" + ("" if n == 10 else _ZH[n - 10])
    if n < 100:
        return _ZH[n // 10] + "十" + ("" if n % 10 == 0 else _ZH[n % 10])
    return str(n)


def words(n, lang):
    n = int(n)
    if lang == "en":
        return en_words(n)
    if lang in ("zh", "ja"):
        return zh_num(n)
    if lang == "es":
        return _ES[n] if n <= 20 else str(n)
    return str(n)


def _fmt_float(x, nd):
    s = f"{x:.{nd}f}"
    return s


# ------------------------------------------------------------------ typed slot values
class Val:
    def fmt(self, lang, rng, now_min):
        raise NotImplementedError


class Plain(Val):
    """Same in every language (names, ids)."""

    def __init__(self, s):
        self.s = str(s)

    def fmt(self, lang, rng, now_min):
        return self.s


class Choice(Val):
    """A short phrase with per-language variants: Choice({'en': [...], 'zh': [...], ...})."""

    def __init__(self, variants):
        self.v = variants

    def fmt(self, lang, rng, now_min):
        opts = self.v.get(lang) or self.v.get("en")
        return rng.choice(opts) if isinstance(opts, (list, tuple)) else str(opts)


class Num(Val):
    def __init__(self, x, nd=0, approx_ok=True, words_ok=True):
        self.x, self.nd, self.approx_ok, self.words_ok = x, nd, approx_ok, words_ok

    def fmt(self, lang, rng, now_min):
        x, nd = self.x, self.nd
        is_int = abs(x - round(x)) < 1e-9
        u = rng.random()
        if self.words_ok and is_int and 0 <= x <= 20 and u < 0.3:
            return words(round(x), lang)
        if self.approx_ok and u < 0.45:
            return {"en": "~", "zh": "约", "ja": "約", "es": "~"}[lang] + _fmt_float(x, nd)
        return _fmt_float(x, nd)


class Time(Val):
    """An absolute instant, minutes from the start of the campaign (day 1 00:00 on the site clock, UTC).
    tz_ok: may be written in UTC+8 with an explicit marker. rel_ok: may be written relative to the message time."""

    def __init__(self, minute, tz_ok=False, rel_ok=True, minute_res=1):
        self.m, self.tz_ok, self.rel_ok, self.res = int(round(minute)), tz_ok, rel_ok, minute_res

    def fmt(self, lang, rng, now_min):
        m = self.m
        if self.rel_ok and now_min is not None and rng.random() < 0.25:
            diff = m - now_min
            if diff != 0 and abs(diff) % 60 == 0 and abs(diff) <= 48 * 60:
                h = abs(diff) // 60
                hs = words(h, lang) if (h <= 12 and rng.random() < 0.4) else str(h)
                return {"en": (f"in {hs} hours" if diff > 0 else f"{hs} hours ago"),
                        "zh": (f"{hs}小时后" if diff > 0 else f"{hs}小时前"),
                        "ja": (f"{hs}時間後" if diff > 0 else f"{hs}時間前"),
                        "es": (f"dentro de {hs} horas" if diff > 0 else f"hace {hs} horas")}[lang]
            if diff != 0 and abs(diff) < 180:
                mins = abs(diff)
                return {"en": (f"in {mins} min" if diff > 0 else f"{mins} min ago"),
                        "zh": (f"{mins}分钟后" if diff > 0 else f"{mins}分钟前"),
                        "ja": (f"{mins}分後" if diff > 0 else f"{mins}分前"),
                        "es": (f"dentro de {mins} minutos" if diff > 0 else f"hace {mins} minutos")}[lang]
        tz = ""
        if self.tz_ok and rng.random() < 0.35:
            m += 480
            tz = rng.choice({"en": [" BJT", " (Beijing time, UTC+8)", " UTC+8", " local (UTC+8)"],
                             "zh": [" 北京时间", "（北京时间）", "（UTC+8）"],
                             "ja": [" 北京時間", "（UTC+8）"],
                             "es": [" hora de Pekín", " (UTC+8)"]}[lang])
        d, r = divmod(m, 1440)
        d += 1
        hh, mm = divmod(r, 60)
        style = rng.randrange(4)
        if lang == "en":
            if style == 0:
                s = f"day {d} {hh:02d}:{mm:02d}"
            elif style == 1:
                s = f"{hh:02d}:{mm:02d} on day {d}"
            elif style == 2:
                s = f"Day {d}, {hh:02d}{mm:02d}h"
            else:
                h12 = hh % 12 or 12
                ap = "am" if hh < 12 else "pm"
                s = (f"{h12}{ap} on day {words(d, 'en') if d <= 12 else d}" if mm == 0
                     else f"{h12}:{mm:02d} {ap}, day {d}")
        elif lang == "zh":
            s = [f"第{d}天 {hh:02d}:{mm:02d}", f"第{zh_num(d)}天{hh}点" + (f"{mm}分" if mm else ""),
                 f"{d}号{hh:02d}:{mm:02d}", f"第{d}天{hh}时{mm:02d}分"][style]
        elif lang == "ja":
            s = [f"{d}日目 {hh:02d}:{mm:02d}", f"{d}日目の{hh}時" + (f"{mm}分" if mm else ""),
                 f"Day{d} {hh:02d}:{mm:02d}", f"{zh_num(d)}日目 {hh}時{mm:02d}分"][style]
        else:
            s = [f"día {d} a las {hh:02d}:{mm:02d}", f"el día {d}, {hh}h{mm:02d}",
                 f"jornada {d}, {hh:02d}:{mm:02d}", f"las {hh:02d}:{mm:02d} del día {d}"][style]
        return s + tz


class Dur(Val):
    """A duration in hours (unit='h') or days (unit='d'); may be re-expressed in other units."""

    def __init__(self, value, unit="h", nd=0, approx=False):
        self.v, self.unit, self.nd, self.approx = value, unit, nd, approx

    def fmt(self, lang, rng, now_min):
        hours = self.v * (24 if self.unit == "d" else 1)
        opts = []
        if self.unit == "d":
            opts.append(("d", self.v))
            if abs(hours - round(hours)) < 1e-9:
                opts.append(("h", round(hours)))
        else:
            opts.append(("h", self.v))
            if hours <= 4 and abs(hours * 60 - round(hours * 60)) < 1e-9:
                opts.append(("min", round(hours * 60)))
            if hours >= 24 and abs(hours / 24 - round(hours / 24, 1)) < 1e-9:
                opts.append(("d", round(hours / 24, 1)))
        unit, x = rng.choice(opts)
        is_int = abs(x - round(x)) < 1e-9
        if is_int and 0 < x <= 12 and rng.random() < 0.3:
            n = words(round(x), lang)
        else:
            n = str(int(round(x))) if is_int else f"{x:.{max(1, self.nd)}f}"
        pre = ({"en": "about ", "zh": "大约", "ja": "約", "es": "unos "}[lang] if self.approx and rng.random() < 0.6 else "")
        U = {"en": {"h": rng.choice([" h", " hours", " hrs", "-hour"]), "min": rng.choice([" min", " minutes"]), "d": rng.choice([" days", " d"])},
             "zh": {"h": rng.choice(["小时", "个小时"]), "min": "分钟", "d": "天"},
             "ja": {"h": "時間", "min": "分", "d": "日"},
             "es": {"h": rng.choice([" horas", " h"]), "min": " minutos", "d": " días"}}[lang][unit]
        if lang == "en" and U == "-hour":
            U = " hours"
        return f"{pre}{n}{U}"


class Coord(Val):
    """Sky position: decimal degrees or sexagesimal, sometimes in a single 'RA, Dec' token."""

    def __init__(self, ra, dec, nd=4):
        self.ra, self.dec, self.nd = ra, dec, nd

    def fmt(self, lang, rng, now_min):
        style = rng.randrange(3)
        if style == 0:
            return f"RA {self.ra:.{self.nd}f}, Dec {self.dec:+.{self.nd}f}"
        if style == 1:
            return f"({self.ra:.{self.nd}f}, {self.dec:+.{self.nd}f}) deg"
        ra_h = self.ra / 15.0
        h = int(ra_h); m = int((ra_h - h) * 60); s = ((ra_h - h) * 60 - m) * 60
        sg = "-" if self.dec < 0 else "+"
        ad = abs(self.dec); d = int(ad); dm = int((ad - d) * 60); ds = ((ad - d) * 60 - dm) * 60
        return f"{h:02d}:{m:02d}:{s:05.2f} {sg}{d:02d}:{dm:02d}:{ds:04.1f}"


class Ref(Val):
    """Reference to an earlier message by its number."""

    def __init__(self, msg):
        self.msg = msg

    def fmt(self, lang, rng, now_min):
        n = self.msg["id"]
        return rng.choice({"en": [f"#{n}", f"msg {n}", f"message #{n}", f"our note #{n}"],
                           "zh": [f"#{n}", f"第{n}条消息", f"{n}号通知"],
                           "ja": [f"#{n}", f"{n}番の連絡"],
                           "es": [f"#{n}", f"el mensaje {n}", f"nuestro aviso n.º {n}"]}[lang])


# ------------------------------------------------------------------ pools + rendering
def load_pool(problem_dir: str, seed: int) -> dict:
    name = os.path.basename(os.path.normpath(problem_dir))
    # organizer-only measurement switch (set in the runner's environment, never visible to agents): write a hidden
    # seed's messages with the public dev authors, to measure how much a parser loses when the authors change
    if os.environ.get("AOH_NL_FORCE_DEV_POOL") == "1":
        seed = 0
    if seed >= HIDDEN_SEED_MIN:
        path = os.path.join(ROOT, "_hidden", "nl", f"{name}.json")
    else:
        path = os.path.join(problem_dir, "nl_pool_dev.json")
    if os.path.exists(path + ".selected"):  # pools are never overwritten; a pointer names the one in use
        path = os.path.join(os.path.dirname(path), open(path + ".selected").read().strip())
    with open(path) as f:
        return json.load(f)


def slots_of(template: str):
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


class Board:
    """Collects messages (time, kind, slots), assigns numbers in time order and renders them."""

    def __init__(self, pool: dict, seed: int, salt: int = 0):
        self.pool = pool["kinds"]
        self.rng = random.Random(seed * 1000003 + 77 + salt)
        self.msgs = []

    def add(self, t, kind, **slots):
        if kind not in self.pool:
            raise KeyError(f"no templates for kind {kind!r}")
        m = {"t": t, "kind": kind, "slots": slots, "id": None, "text": None}
        self.msgs.append(m)
        return m

    def finalize(self, minute_of=lambda t: t):
        self.msgs.sort(key=lambda m: m["t"])
        for i, m in enumerate(self.msgs):
            m["id"] = i + 1
        for m in self.msgs:
            m["text"] = self.render(m["kind"], m["slots"], minute_of(m["t"]))
        return self.msgs

    def render(self, kind, slots, now_min=None):
        rng = self.rng
        langs = [l for l in LANG_WEIGHTS if any(e["lang"] == l for e in self.pool[kind])]
        lang = rng.choices(langs, weights=[LANG_WEIGHTS[l] for l in langs])[0]
        cands = [e["t"] for e in self.pool[kind] if e["lang"] == lang]
        tpl = rng.choice(cands)
        vals = {k: (v.fmt(lang, rng, now_min) if isinstance(v, Val) else str(v)) for k, v in slots.items()}
        return tpl.format(**vals)
