"""Model client abstraction.

Agents talk to an ``LLMClient``. Two implementations:

* ``AnthropicClient`` - the Claude Messages API with structured JSON outputs
  (``output_config.format``), adaptive thinking, effort, prompt caching on the
  stable system blocks, the server-side refusal fallback, streaming, and a
  validation-retry loop that feeds the Pydantic error back to the model.
* ``MockClient`` - offline; per-agent handler functions or recorded replies.
  The whole pipeline runs on it in tests.

Swapping providers later = another implementation of ``LLMClient``.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from pydantic import BaseModel, ValidationError


# --------------------------------------------------------------------- types

@dataclass
class SystemBlock:
    text: str
    cache: bool = False             # stable text (rules, style guide, glossary): cached prefix


@dataclass
class Image:
    data: bytes
    media_type: str = "image/jpeg"


@dataclass
class LLMRequest:
    agent: str
    system: list[SystemBlock]
    user_text: str
    output: type[BaseModel]
    model: str
    effort: str = "high"
    max_tokens: int = 16000
    images: list[Image] = field(default_factory=list)
    payload: Any = None             # structured input (for mocks and the audit); not sent separately
    prompt_version: str = "v1"


@dataclass
class LLMResult:
    data: BaseModel
    model: str
    usage: dict
    latency_s: float
    retries: int
    request_id: Optional[str] = None
    raw_text: str = ""
    stop_reason: Optional[str] = None


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def call(self, req: LLMRequest) -> LLMResult: ...


# ----------------------------------------------------------- schema helpers

_DROP = {"title", "default", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
         "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "pattern", "examples"}


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema -> structured-output schema: every object closed
    (additionalProperties false) and every property required (optional values
    are expressed as nullable)."""
    s = copy.deepcopy(model.model_json_schema())

    def walk(n):
        if isinstance(n, dict):
            for k in list(n):
                if k in _DROP:
                    n.pop(k)
            if n.get("type") == "object" or "properties" in n:
                n["additionalProperties"] = False
                n["required"] = list(n.get("properties", {}).keys())
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(s)
    return s


def request_fingerprint(req: LLMRequest) -> str:
    h = hashlib.sha256()
    h.update(req.agent.encode())
    for b in req.system:
        h.update(b.text.encode())
    h.update(req.user_text.encode())
    for im in req.images:
        h.update(hashlib.sha256(im.data).digest())
    return h.hexdigest()[:24]


# --------------------------------------------------------------- Anthropic

KEY_VARS = ("CERTIFLOW_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")


def api_key_from_env() -> Optional[str]:
    """CertiFlow's own variable first: hosted coding sessions may reserve ANTHROPIC_API_KEY for
    themselves and not pass it to commands. Returns None to let the SDK resolve credentials."""
    import os
    for v in KEY_VARS:
        if os.environ.get(v, "").strip():
            return os.environ[v].strip()
    return None

class AnthropicClient:
    """Claude Messages API. The API key is read by the SDK from the server
    environment (ANTHROPIC_API_KEY); it is never passed around in code."""

    def __init__(self, fallbacks: Optional[str] = "default", validation_retries: int = 2,
                 max_backoff_retries: int = 4):
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key_from_env(), max_retries=2)
        self.fallbacks = fallbacks
        self.validation_retries = validation_retries
        self.max_backoff_retries = max_backoff_retries

    def _content(self, req: LLMRequest, text: str) -> list[dict]:
        blocks: list[dict] = []
        for im in req.images:
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": im.media_type,
                                                        "data": base64.standard_b64encode(im.data).decode()}})
        blocks.append({"type": "text", "text": text})
        return blocks

    def _stream(self, **kw):
        if self.fallbacks:
            return self.client.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"], fallbacks=self.fallbacks, **kw)
        return self.client.messages.stream(**kw)

    def _send(self, kw: dict):
        """Stream (long outputs) with backoff on rate limits / overload beyond the SDK's own retries."""
        a = self._anthropic
        for attempt in range(self.max_backoff_retries + 1):
            try:
                with self._stream(**kw) as stream:
                    return stream.get_final_message()
            except (a.RateLimitError, a.InternalServerError, a.APIConnectionError) as e:
                if attempt == self.max_backoff_retries:
                    raise LLMError(f"{type(e).__name__}: {e}") from e
                time.sleep(min(60.0, 2 ** attempt + random.uniform(0, 1)))
            except a.APIStatusError as e:
                if e.status_code >= 500 and attempt < self.max_backoff_retries:
                    time.sleep(min(60.0, 2 ** attempt + random.uniform(0, 1)))
                    continue
                raise LLMError(f"API error {e.status_code}: {e.message}") from e

    def call(self, req: LLMRequest) -> LLMResult:
        schema = strict_schema(req.output)
        system = [{"type": "text", "text": b.text, **({"cache_control": {"type": "ephemeral"}} if b.cache else {})}
                  for b in req.system]
        messages: list[dict] = [{"role": "user", "content": self._content(req, req.user_text)}]
        usage_total: dict[str, int] = {}
        t0 = time.time()
        last_err = None
        for attempt in range(self.validation_retries + 1):
            msg = self._send(dict(model=req.model, max_tokens=req.max_tokens, system=system, messages=messages,
                                  thinking={"type": "adaptive"},
                                  output_config={"effort": req.effort,
                                                 "format": {"type": "json_schema", "schema": schema}}))
            u = msg.usage
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                usage_total[k] = usage_total.get(k, 0) + int(getattr(u, k, 0) or 0)
            if msg.stop_reason == "refusal":
                raise LLMError(f"{req.agent}: the model declined this request")
            if msg.stop_reason == "max_tokens":
                raise LLMError(f"{req.agent}: output hit max_tokens ({req.max_tokens}); raise it in config/agents.json")
            text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
            try:
                data = req.output.model_validate_json(text)
                return LLMResult(data=data, model=msg.model, usage=usage_total, latency_s=time.time() - t0,
                                 retries=attempt, request_id=getattr(msg, "_request_id", None), raw_text=text,
                                 stop_reason=msg.stop_reason)
            except ValidationError as e:
                last_err = e
                messages = messages + [
                    # pass the reply back unchanged (thinking blocks included): edited history is rejected
                    {"role": "assistant", "content": msg.content},
                    {"role": "user", "content": f"That output failed validation:\n{e}\nReturn the corrected JSON only."},
                ]
        raise LLMError(f"{req.agent}: invalid output after {self.validation_retries} retries: {last_err}")


# ---------------------------------------------------------------------- mock

Handler = Callable[[LLMRequest], dict]


class MockClient:
    """Offline client. ``handlers[agent](req) -> dict`` produces the reply, or a
    recordings directory supplies replies keyed by request fingerprint."""

    def __init__(self, handlers: dict[str, Handler] | None = None, recordings: Path | None = None,
                 model_name: str = "mock"):
        self.handlers = handlers or {}
        self.recordings = recordings
        self.model_name = model_name
        self.calls: list[LLMRequest] = []

    def call(self, req: LLMRequest) -> LLMResult:
        self.calls.append(req)
        if req.agent in self.handlers:
            raw = self.handlers[req.agent](req)
        elif self.recordings and (self.recordings / f"{request_fingerprint(req)}.json").exists():
            raw = json.loads((self.recordings / f"{request_fingerprint(req)}.json").read_text("utf-8"))
        else:
            raise LLMError(f"mock: no handler or recording for agent '{req.agent}'")
        text = json.dumps(raw, ensure_ascii=False)
        data = req.output.model_validate(raw)
        n_in = (sum(len(b.text) for b in req.system) + len(req.user_text)) // 4
        return LLMResult(data=data, model=self.model_name, latency_s=0.0, retries=0, raw_text=text,
                         usage={"input_tokens": n_in, "output_tokens": len(text) // 4,
                                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})


class RecordingClient:
    """Wraps a real client and saves every reply, so tests can replay real runs offline."""

    def __init__(self, inner: LLMClient, out_dir: Path):
        self.inner, self.out = inner, out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

    def call(self, req: LLMRequest) -> LLMResult:
        res = self.inner.call(req)
        (self.out / f"{request_fingerprint(req)}.json").write_text(res.raw_text, "utf-8")
        return res
