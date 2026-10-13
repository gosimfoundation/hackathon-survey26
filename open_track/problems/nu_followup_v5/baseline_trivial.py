"""Trivial baseline: point at the newest observable alert's notice position, never report."""
from aohkit.agent_base import serve


def decide(init, s):
    up = [a for a in s["alerts"] if a["observable_tonight"]]
    if not up:
        return {"type": "wait"}
    a = up[-1]
    return {"type": "observe", "ra": a["ra_deg"], "dec": a["dec_deg"]}


serve(decide)
