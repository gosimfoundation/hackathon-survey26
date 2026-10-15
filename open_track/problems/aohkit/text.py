"""Shared helpers for natural-language intel: paraphrase, number words, hedging, sources."""
import random

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n: int) -> str:
    n = int(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    return str(n)


def num(rng: random.Random, x: float, nd: int = 1, allow_words: bool = True) -> str:
    """Render a number in one of several styles (digits, words, approx)."""
    style = rng.random()
    if allow_words and abs(x - round(x)) < 1e-9 and 0 <= x < 100 and style < 0.25:
        return words(int(round(x)))
    if style < 0.4:
        return f"~{x:.{max(nd - 1, 0)}f}"
    return f"{x:.{nd}f}"


def pick(rng: random.Random, *options: str) -> str:
    return rng.choice(options)


def hedge(rng: random.Random, credibility: float) -> str:
    if credibility > 0.8:
        return pick(rng, "", "We confirm that", "Our analysis shows", "It is established that")
    if credibility > 0.5:
        return pick(rng, "Preliminary:", "We tentatively report that", "Initial inspection suggests", "")
    return pick(rng, "Unconfirmed rumour:", "Someone on the night channel said", "Possibly,", "Hearsay from the control room:")


def hhmm(minutes_from_start: int, base_hour: int = 0) -> str:
    m = int(minutes_from_start) + base_hour * 60
    d, m = divmod(m, 1440)
    return f"day {d + 1} {m // 60:02d}:{m % 60:02d}"
