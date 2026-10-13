"""Assisted-mode helper: drives the OFFICIAL basic example agent in-process.

The assistant is ``py/basic_example`` run rule-only (OBSERVER_MODEL_DISABLED=1, set
below BEFORE importing agent_core — the module files are never modified). The call
sequence mirrors ``py/basic_example/agent.py`` exactly:

    state = SurveyState(init_payload); planner = Planner(state, log=...)
    per decision:
        planner.clock.start_decision()
        action = planner.decide(request["payload"])
        action = validate_action(action, state, planner.consecutive_reports)
        (ActionRejected -> fallback_action("validation-rejected"),
         any other exception -> fallback_action("planner-exception"))
    on commit (suggestion or a human action):
        planner.note_action(action)   # keeps consecutive_reports consistent
        planner.clock.end_decision()

Requests are built with ``V4Workflow.request_message(seq, snapshot, {})`` — the EMPTY
wallclock dict gives the planner an infinite budget (pace level 0), so the run is
deterministic. Envelope keys are stripped from the suggestion exactly as
``V4Workflow.action_from_response`` does, so the committed action is legal for
``v4_runner.normalize_action``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["OBSERVER_MODEL_DISABLED"] = "1"  # rule-only, no network — before agent_core import

_APP_ROOT = os.environ.get("AOH_APP_ROOT", "/app")
for _p in (_APP_ROOT + "/py", _APP_ROOT + "/py/basic_example"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agent_core.planner import Planner  # noqa: E402
from agent_core.state import SurveyState  # noqa: E402
from agent_core.validation import ActionRejected, fallback_action, validate_action  # noqa: E402
from challenge.v4_workflow import ENVELOPE_KEYS, V4Workflow  # noqa: E402


def _silent_log(_text: str) -> None:
    pass


class Assistant:
    """One basic-example planner bound to one card run."""

    def __init__(self, card_root: str) -> None:
        self.workflow = V4Workflow(Path(card_root))
        payload = self.workflow.initialize_payload(86400)
        self.state = None
        self.planner = None
        try:
            self.state = SurveyState(payload)
            self.planner = Planner(self.state, log=_silent_log)
        except Exception:
            # mirror agent.py: a failed initialize means "fall back on every decision"
            self.state = None
            self.planner = None

    def suggest(self, seq: int, snapshot: dict) -> dict:
        """The action the basic example would send for this decision (envelope-stripped)."""
        if self.planner is None:
            action = fallback_action("not initialized")
        else:
            request = V4Workflow.request_message(seq, snapshot, {})
            self.planner.clock.start_decision()
            try:
                action = self.planner.decide(request["payload"])
                action = validate_action(action, self.state, self.planner.consecutive_reports)
            except ActionRejected:
                action = fallback_action("validation-rejected")
            except Exception:
                action = fallback_action("planner-exception")
        return {key: value for key, value in action.items() if key not in ENVELOPE_KEYS}

    def note(self, committed_action: dict) -> None:
        """Mirror agent.py: note_action + clock.end_decision after each decision.

        Called with the COMMITTED action (the suggestion or a human action) so the
        assistant's state stays consistent when the human takes over."""
        if self.planner is None:
            return
        self.planner.note_action(committed_action)
        self.planner.clock.end_decision()
