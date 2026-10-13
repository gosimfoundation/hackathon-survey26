"""Optional, budgeted LLM helper for contestant agents (v2: through the runner's proxy).

The runner starts a localhost proxy locked to one model — tokenflux `Deepseek/deepseek-flash` (pi's default) —
meters every call itself and charges the cost against the score. Agents never see an API key.
Usage inside an agent:   from aohkit.llm import ask;  text = ask("...", max_tokens=300)
"""
import json, os, sys, urllib.request

MODEL = "Deepseek/deepseek-flash"


def ask(prompt, system="You are a concise assistant. Answer briefly.", max_tokens=400):
    url = os.environ.get("AOH_LLM_PROXY")
    if not url:
        raise RuntimeError("aohkit.llm is only available when the agent runs under aohkit.runner")
    body = json.dumps({"prompt": str(prompt), "system": str(system), "max_tokens": int(max_tokens)}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=150) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["text"]


if __name__ == "__main__":
    print(ask(" ".join(sys.argv[1:]) or "Say OK."))
