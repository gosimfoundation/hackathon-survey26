"""Trivial baseline: never alert."""
from aohkit.agent_base import serve
serve(lambda init, s: {"type": "wait"})
