"""Trivial baseline: physics every block, never calibrate or flag."""
from aohkit.agent_base import serve
serve(lambda init, s: {"mode": "physics"})
