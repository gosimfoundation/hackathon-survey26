"""Runner-side LLM proxy: fixed model, metered by the organizer (the agent cannot skip or edit the ledger).
v2.1: transient upstream errors (disconnects, 5xx, 429) are retried up to 3 times; failed calls are never metered.
v2.2 (2026-10-12, defaults unchanged): AOH_LLM_UPSTREAM sends upstream calls to another OpenAI-compatible base URL
(the organizer relay aohkit/pi_proxy.py, which holds the real key; a dummy key is sent) and AOH_LLM_PROXY_PORTS
(comma list) binds one of these fixed localhost ports instead of a random one (needed inside pi's sandbox)."""
import json, os, subprocess, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "Deepseek/deepseek-flash"
BASE = os.environ.get("AOH_LLM_UPSTREAM") or "https://tokenflux.dev/v1"
_RELAYED = bool(os.environ.get("AOH_LLM_UPSTREAM"))
_OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({})).open if _RELAYED else urllib.request.urlopen
MAX_CALLS = 200
_key = None


def _api_key():
    global _key
    if _RELAYED:
        return "relay-held-key"
    if _key is None:
        _key = subprocess.run(["/opt/homebrew/bin/pi", "auth", "print-api-key", "--provider", "tokenflux"],
                              capture_output=True, text=True, timeout=60, cwd="/tmp").stdout.strip()
    return _key


def start(ledger_path):
    lock = threading.Lock()
    state = {"calls": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                with lock:
                    if state["calls"] >= MAX_CALLS:
                        raise RuntimeError(f"LLM call cap ({MAX_CALLS}) reached")
                    state["calls"] += 1
                body = {"model": MODEL, "max_tokens": max(1, min(int(req.get("max_tokens", 400)), 1500)),
                        "messages": [{"role": "system", "content": str(req.get("system", ""))[:20000]},
                                     {"role": "user", "content": str(req.get("prompt", ""))[:60000]}]}
                r = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                           headers={"Authorization": "Bearer " + _api_key(), "Content-Type": "application/json"})
                t0 = time.time()
                out, last = None, None
                for attempt in range(4):  # transient upstream failures are retried; only a success is metered
                    try:
                        with _OPEN(r, timeout=120) as resp:
                            out = json.loads(resp.read())
                        break
                    except Exception as e:
                        last = e
                        if isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429:
                            break
                        time.sleep(2 * (attempt + 1))
                if out is None:
                    raise last
                u = out.get("usage") or {}
                with lock, open(ledger_path, "a") as f:
                    f.write(json.dumps({"t": round(time.time() - t0, 2), "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}) + "\n")
                payload = {"text": out["choices"][0]["message"]["content"]}
            except Exception as e:  # report, never crash the runner
                payload = {"error": f"{type(e).__name__}: {e}"}
            data = json.dumps(payload).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    ports = [int(x) for x in (os.environ.get("AOH_LLM_PROXY_PORTS") or "0").split(",") if x.strip()]
    srv, last = None, None
    for port in ports:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), H); break
        except OSError as e:
            last = e
    if srv is None:
        raise last
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/ask"
