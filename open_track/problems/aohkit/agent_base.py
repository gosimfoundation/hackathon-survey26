"""Minimal protocol loop for agents: subclass-free, pass a decide(init, snapshot) -> action function."""
import json, sys


def serve(decide, on_init=None):
    init = None
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mt = msg.get("message_type")
        if mt == "initialize":
            init = msg["payload"]
            if on_init:
                on_init(init)
        elif mt == "decision_request":
            try:
                action = decide(init, msg["payload"])
            except Exception as e:  # never crash the protocol loop
                print(f"decide error: {e!r}", file=sys.stderr)
                action = {"type": "wait"}
            sys.stdout.write(json.dumps({"protocol_version": "aoh-protocol-v1", "message_type": "decision_response",
                                         "decision_sequence": msg["decision_sequence"], "action": action}) + "\n")
            sys.stdout.flush()
        elif mt == "finished":
            break
