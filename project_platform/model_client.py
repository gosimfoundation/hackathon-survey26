"""Small non-streaming OpenAI-compatible client for preparation jobs."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .manifest import ProjectError
from .session import _NoRedirect

# The proxy gives up on the team's model after 110-120 s, and on an unanswered open
# Participate page relay after 125 s, then answers with a code. Wait longer than
# that, but below the 150 s Edge request limit, so the code arrives before a retry.
MODEL_TIMEOUT=140
_ADAPT=" Use a faster model or endpoint, or add observer.project.json so no automatic adaptation is needed."
# Failures after the proxy accepted the call. Retrying the same idempotent call
# cannot help and would only report 409, so these are explained at once.
_FINAL={
    "model_provider_timeout":"Your model API took longer than the two-minute limit to answer."+_ADAPT,
    "model_provider_unavailable":"Your model API could not be reached or did not answer in time. "
        "Check the API endpoint on the Participate page."+_ADAPT,
    "personal_api_not_connected":"No open Participate page answered the model request. Your team does not save "
        "its model key, so keep the Participate page open with the model API connected while the project is prepared, "
        "or save the key there, or add observer.project.json so no automatic adaptation is needed.",
    "personal_model_failed":"Your model API failed or did not answer in time through the open Participate page. "
        "Check the API endpoint, model name, key and balance."+_ADAPT,
}
# Provider answers that usually clear up on their own (rate limit, overloaded or
# restarting gateway). These are retried once as a new call with a new key.
TRANSIENT_PROVIDER_STATUS=frozenset({429,500,502,503,504})
PROVIDER_RETRY_DELAY=5.0


class _TransientProviderError(Exception):
    pass


class ModelClient:
    def __init__(self, base_url: str, credential: str, *, timeout: float = MODEL_TIMEOUT):
        parsed=urllib.parse.urlsplit(base_url)
        if parsed.scheme!="https" and not (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1")):
            raise ProjectError("Model proxy must use HTTPS except in local tests.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProjectError("Invalid model proxy URL.")
        self.url=base_url.rstrip("/")+"/chat/completions"
        self.credential=credential
        self.timeout=timeout
        self.opener=urllib.request.build_opener(_NoRedirect())

    def __call__(self, body: dict) -> dict:
        payload=json.dumps(body,allow_nan=False).encode()
        if len(payload)>65536:
            raise ProjectError("Model request exceeds the proxy size limit.")
        try:
            return self._call(payload)
        except _TransientProviderError:
            # The earlier call is finished (the provider answered), so a new
            # Idempotency-Key is a new call, not a duplicate of an accepted one.
            time.sleep(PROVIDER_RETRY_DELAY)
        try:
            return self._call(payload)
        except _TransientProviderError as exc:
            raise ProjectError(str(exc)) from None

    def _call(self, payload: bytes) -> dict:
        call_id=str(uuid.uuid4())
        earlier=None
        for attempt in range(3):
            request=urllib.request.Request(self.url,data=payload,method="POST",
                headers={"Authorization":"Bearer "+self.credential,"Content-Type":"application/json",
                         "Idempotency-Key":call_id})
            try:
                with self.opener.open(request,timeout=self.timeout) as response:
                    result=response.read(2*1024*1024+1)
                    if len(result)>2*1024*1024:
                        raise ProjectError("Model response is too large.")
                    value=json.loads(result)
                    if not isinstance(value,dict):
                        raise ProjectError("Invalid model response.")
                    return value
            except urllib.error.HTTPError as exc:
                error=_observer_error(exc)
                if error.get("code")=="model_provider_error":
                    # The team's provider answered with an error. Retrying the same
                    # idempotent call cannot help and would only report 409.
                    status=error.get("provider_status")
                    message=("The model provider rejected the request"
                        +(" (HTTP "+str(status)+")" if isinstance(status,int) else "")
                        +". Check the API endpoint, model name, key and balance on the Participate page.")
                    if status in TRANSIENT_PROVIDER_STATUS:
                        raise _TransientProviderError(message) from None
                    raise ProjectError(message) from None
                if error.get("code") in _FINAL:
                    raise ProjectError(_FINAL[error["code"]]) from None
                if exc.code==403:
                    raise ProjectError("No model API is set up for your team. Set one under Model API on the Participate page, "
                                       "or add observer.project.json so no automatic adaptation is needed.") from None
                if exc.code==409:
                    # A retry of this same call: the first attempt was accepted but
                    # its answer never arrived here. Report that, not the duplicate.
                    raise ProjectError(earlier or "The model request was already received. "
                                       "Review the preparation status before retrying.") from None
                if exc.code<500 or attempt==2:
                    raise ProjectError("Model call failed (HTTP "+str(exc.code)+").") from None
                earlier="Model call failed (HTTP "+str(exc.code)+")."
            except (urllib.error.URLError,TimeoutError,ConnectionError) as exc:
                timed_out=isinstance(exc,TimeoutError) or isinstance(getattr(exc,"reason",None),TimeoutError)
                earlier=("Your model API did not answer within "+format(self.timeout,"g")+" seconds."+_ADAPT
                         if timed_out else "Model service is unavailable.")
                if attempt==2:
                    raise ProjectError(earlier) from None
            time.sleep(0.25*(attempt+1))
        raise ProjectError("Model service is unavailable.")


def _observer_error(exc: urllib.error.HTTPError) -> dict:
    """The proxy's fixed error object ({code, provider_status}); never provider text."""
    try:
        value=json.loads(exc.read(4096)).get("error")
    except (ValueError,AttributeError,OSError):
        return {}
    if not isinstance(value,dict):
        return {}
    status=value.get("provider_status")
    return {"code":str(value.get("code",""))[:80],
            "provider_status":status if isinstance(status,int) and 100<=status<=599 else None}


# --- Direct model access (team variables; no platform model proxy) -------------------------
# Preparation's automatic adaptation can call the team's own provider with the team's
# variables (OPENAI_* or ANTHROPIC_*), exactly as the team's program does during an
# evaluation. Only https bases on the team's allowed domains are used, and no provider
# text ever reaches an error message.
DIRECT_TIMEOUT=120.0


def team_model_client(team: dict, *, timeout: float = DIRECT_TIMEOUT, allow_local: bool = False):
    """(completion, model) from the team's variables, or a ProjectError naming what is missing."""
    environment=team.get("environment") or {}
    domains=set(team.get("domains") or ())
    for prefix,protocol,default in (("OPENAI","openai","https://api.openai.com/v1"),
                                    ("ANTHROPIC","anthropic","https://api.anthropic.com")):
        key=environment.get(prefix+"_API_KEY")
        if not key:
            continue
        model=environment.get(prefix+"_MODEL")
        if not model:
            raise ProjectError("Automatic adaptation uses your team's model: add the variable "+prefix+"_MODEL "
                               "under Keys and network, or add observer.project.json so no automatic adaptation is needed.")
        base=(environment.get(prefix+"_BASE_URL") or default).rstrip("/")
        parsed=urllib.parse.urlsplit(base)
        local=allow_local and parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1")
        if not local and (parsed.scheme!="https" or parsed.username or parsed.password or parsed.query
                          or parsed.fragment or (parsed.hostname or "").lower() not in domains):
            raise ProjectError("Automatic adaptation calls "+prefix+"_BASE_URL directly: it must be an https address "
                               "on one of your team's allowed domains (Keys and network).")
        return DirectModelClient(protocol,base,key,timeout=timeout),model
    raise ProjectError("Automatic adaptation uses your team's model: save OPENAI_API_KEY (or ANTHROPIC_API_KEY) with "
                       "its _BASE_URL and _MODEL under Keys and network, or add observer.project.json so no "
                       "automatic adaptation is needed.")


class DirectModelClient:
    """One OpenAI-shaped completion call against the team's provider (OpenAI or Anthropic protocol)."""
    def __init__(self, protocol: str, base: str, key: str, *, timeout: float = DIRECT_TIMEOUT):
        if protocol not in ("openai","anthropic"):
            raise ProjectError("Unknown model protocol.")
        self.protocol=protocol
        self.url=base.rstrip("/")+("/chat/completions" if protocol=="openai" else "/v1/messages")
        self.key=key
        self.timeout=timeout
        self.opener=urllib.request.build_opener(_NoRedirect())

    def _body(self, body: dict) -> dict:
        # Some providers (Kimi Coding Plan) refuse temperature; the adapter prompt does not need it.
        if self.protocol=="openai":
            return {k:v for k,v in body.items() if k!="temperature"}
        system="\n\n".join(m["content"] for m in body["messages"] if m["role"]=="system")
        messages=[{"role":m["role"],"content":m["content"]} for m in body["messages"] if m["role"]!="system"]
        return {"model":body["model"],"max_tokens":body.get("max_tokens",4096),"system":system,"messages":messages}

    def _headers(self) -> dict:
        if self.protocol=="openai":
            return {"Authorization":"Bearer "+self.key,"Content-Type":"application/json"}
        return {"x-api-key":self.key,"anthropic-version":"2023-06-01","Content-Type":"application/json"}

    def __call__(self, body: dict) -> dict:
        payload=json.dumps(self._body(body),allow_nan=False).encode()
        for attempt in range(2):
            request=urllib.request.Request(self.url,data=payload,method="POST",headers=self._headers())
            try:
                with self.opener.open(request,timeout=self.timeout) as response:
                    raw=response.read(2*1024*1024+1)
                if len(raw)>2*1024*1024:
                    raise ProjectError("Model response is too large.")
                value=json.loads(raw)
                if not isinstance(value,dict):
                    raise ProjectError("Invalid model response.")
                return value if self.protocol=="openai" else _anthropic_as_chat(value)
            except urllib.error.HTTPError as exc:
                message=("The model provider rejected the request (HTTP "+str(exc.code)+"). Check the API "
                         "endpoint, model name, key and balance under Keys and network.")
                if exc.code not in TRANSIENT_PROVIDER_STATUS or attempt:
                    raise ProjectError(message) from None
            except (urllib.error.URLError,TimeoutError,ConnectionError,ValueError) as exc:
                if attempt:
                    timed_out=isinstance(exc,TimeoutError) or isinstance(getattr(exc,"reason",None),TimeoutError)
                    raise ProjectError(("Your model API did not answer within "+format(self.timeout,"g")+" seconds."
                                        if timed_out else "Your model API could not be reached.")+_ADAPT) from None
            time.sleep(PROVIDER_RETRY_DELAY)
        raise ProjectError("Your model API could not be reached."+_ADAPT)


def _anthropic_as_chat(value: dict) -> dict:
    blocks=value.get("content")
    if not isinstance(blocks,list):
        raise ProjectError("Invalid model response.")
    text="".join(b.get("text","") for b in blocks if isinstance(b,dict) and b.get("type")=="text")
    return {"choices":[{"message":{"role":"assistant","content":text}}]}
