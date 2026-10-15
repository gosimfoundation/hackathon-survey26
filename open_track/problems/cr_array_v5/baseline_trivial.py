"""Trivial baseline: keep every station in, normal mode, never act."""
from aohkit.agent_base import serve
serve(lambda init, s: {"type": "ops"})
