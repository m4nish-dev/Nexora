"""LiteLLM gateway: response caching + ordered key failover.

Why an ordered key loop around ``litellm.acompletion`` instead of ``litellm.Router``:

* The contract needs deterministic order (key_1 first), an exact ``fallback_attempts`` count
  and *per-request, per-key* failure injection (``X-Simulate-Failure``).
* Router cooldowns are process-wide: a simulated 429 on key_1 would cool key_1 down for later
  real requests, breaking "for this request only". Retries inside a Router model group also
  pick deployments at random, so attempt counts can't be guaranteed.

Every attempt is still a genuine LiteLLM call: LiteLLM does provider translation, exception
mapping, usage accounting and caching. This module only decides which credential goes next
and how to classify what came back.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import litellm
from litellm.caching.caching import Cache

from app.errors import AllProvidersUnavailable, UpstreamRequestRejected
from app.services.failure_simulation import SimulationPlan, simulated_provider_error
from app.services.key_pool import ApiKey, KeyPool

logger = logging.getLogger("nexora.llm")

CompletionFn = Callable[..., Awaitable[Any]]

# Substrings that mark a 4xx as a key-level problem (quota / credential), where another key can help.
_KEY_LEVEL_HINTS = (
    "quota",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "resource has been exhausted",
    "insufficient_quota",
    "billing",
    "api key",
    "api_key",
    "credential",
    "permission",
)


def configure_litellm_cache(*, enabled: bool, ttl_seconds: int, max_items: int) -> bool:
    """Install LiteLLM's built-in in-memory cache. Returns whether caching is active.

    LiteLLM >= 1.110 removed its disk backend; the assignment permits in-memory, and Redis is
    out of scope. The cache key is LiteLLM's hash of model + messages + sampling params
    (``api_key`` is deliberately excluded), so a reply produced by key_2 serves later requests
    on any key.
    """
    litellm.suppress_debug_info = True
    litellm.drop_params = True  # tolerate params a provider doesn't support instead of failing
    if not enabled:
        litellm.cache = None
        return False
    litellm.cache = Cache(
        type="local",
        default_in_memory_ttl=ttl_seconds,
        supported_call_types=["acompletion", "completion"],
    )
    # LiteLLM's InMemoryCache defaults to 200 entries; the bound is an attribute, not a ctor arg.
    litellm.cache.cache.max_size_in_memory = max_items
    _preload_cache_hit_path()
    return True


def _preload_cache_hit_path() -> None:
    """Import the modules LiteLLM loads lazily on the first cache *hit*.

    1. Fail fast: in LiteLLM 1.110 this path needs ``orjson``/``soundfile``; if they were missing,
       every cache hit would raise and be misclassified as a provider failure.
    2. Keep the first cache hit fast (the lazy import costs ~150 ms otherwise).
    """
    try:
        import litellm.llms.anthropic.messages.native.response_cache  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"LiteLLM cache-hit path is missing a dependency: {exc.name}") from exc


def litellm_cache_enabled() -> bool:
    return litellm.cache is not None


async def _await_pending_cache_writes(timeout: float = 2.0) -> None:
    """LiteLLM writes cache entries in a background task after returning a response.

    Waiting for that write makes "send the same message again immediately → LLM_CACHE"
    deterministic instead of depending on scheduling luck.
    """
    try:
        from litellm.caching.caching_handler import _PENDING_CACHE_WRITES
    except ImportError:  # internal name changed in a future LiteLLM version: yield once instead
        await asyncio.sleep(0)
        return
    pending = [task for task in list(_PENDING_CACHE_WRITES) if not task.done()]
    if pending:
        await asyncio.wait(pending, timeout=timeout)


@dataclass(frozen=True, slots=True)
class FailedAttempt:
    key_id: str
    status: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class CompletionResult:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    from_cache: bool
    key_id: str | None
    fallback_attempts: int
    usage_estimated: bool
    failed_attempts: list[FailedAttempt] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Classification:
    retryable: bool
    status: int | None
    reason: str


def classify_provider_error(exc: Exception) -> _Classification:
    """Decide whether a failure is tied to the key/provider (try the next key) or to the request."""
    status = getattr(exc, "status_code", None)
    status = status if isinstance(status, int) else None
    name = type(exc).__name__

    if isinstance(exc, litellm.RateLimitError):
        return _Classification(True, status or 429, "rate limited / quota exhausted")
    if isinstance(exc, litellm.ContextWindowExceededError | litellm.ContentPolicyViolationError):
        return _Classification(False, status or 400, name)
    if isinstance(exc, litellm.AuthenticationError | litellm.PermissionDeniedError):
        return _Classification(True, status, "key rejected by provider")
    if isinstance(exc, litellm.Timeout | litellm.APIConnectionError):
        return _Classification(True, status, "provider unreachable or timed out")
    if isinstance(exc, litellm.BadRequestError | litellm.UnprocessableEntityError):
        message = str(exc).lower()
        if any(hint in message for hint in _KEY_LEVEL_HINTS):
            return _Classification(True, status, "key-level rejection (quota / credential)")
        return _Classification(False, status or 400, name)
    if status is not None and 400 <= status < 500 and status not in (401, 402, 403, 404, 408, 409, 429):
        return _Classification(False, status, name)
    # 5xx, 404 (model not available to this key/project), unknown errors: bounded, try the next key.
    return _Classification(True, status, "provider error")


def _extract_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""
    return content.strip() if isinstance(content, str) else ""


class LLMGateway:
    def __init__(
        self,
        pool: KeyPool,
        *,
        timeout_seconds: float,
        max_output_tokens: int | None = None,
        api_base: str | None = None,
        completion_fn: CompletionFn | None = None,
    ) -> None:
        self._pool = pool
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._api_base = api_base
        # Injectable for tests; production always uses LiteLLM directly.
        self._completion_fn = completion_fn or litellm.acompletion

    @property
    def pool(self) -> KeyPool:
        return self._pool

    async def complete(
        self, messages: list[dict[str, str]], *, simulation: SimulationPlan | None = None
    ) -> CompletionResult:
        failures: list[FailedAttempt] = []
        # An explicit failover demo must exercise the key path, so skip cache *reads* (writes stay on).
        bypass_cache_reads = simulation is not None

        for key in self._pool:
            simulated_status = simulation.status_for(key.key_id) if simulation else None
            try:
                response = await self._completion_fn(
                    **self._request_kwargs(key, messages, simulated_status, bypass_cache_reads)
                )
            except Exception as exc:  # every provider failure is classified below
                verdict = classify_provider_error(exc)
                logger.warning(
                    "llm attempt failed key_id=%s model=%s status=%s retryable=%s simulated=%s error=%s: %s",
                    key.key_id,
                    key.model,
                    verdict.status,
                    verdict.retryable,
                    simulated_status is not None,
                    type(exc).__name__,
                    " ".join(self._pool.redact(str(exc)).split())[:300],
                )
                if not verdict.retryable:
                    raise UpstreamRequestRejected() from exc
                failures.append(FailedAttempt(key.key_id, verdict.status, verdict.reason))
                continue

            text = _extract_text(response)
            if not text:
                # Empty completions (e.g. safety-filtered) aren't key failures; another key yields the same.
                logger.warning("llm returned empty content key_id=%s model=%s", key.key_id, key.model)
                raise UpstreamRequestRejected("upstream provider returned an empty response")

            from_cache = bool((getattr(response, "_hidden_params", None) or {}).get("cache_hit"))
            if not from_cache:
                await _await_pending_cache_writes()
            input_tokens, output_tokens, estimated = self._usage(response, key.model, messages, text)

            logger.info(
                "llm success key_id=%s model=%s source=%s fallback_attempts=%d in=%d out=%d",
                None if from_cache else key.key_id,
                key.model,
                "LLM_CACHE" if from_cache else "LIVE_INFERENCE",
                0 if from_cache else len(failures),
                input_tokens,
                output_tokens,
            )
            return CompletionResult(
                content=text,
                model=key.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                from_cache=from_cache,
                key_id=None if from_cache else key.key_id,
                fallback_attempts=0 if from_cache else len(failures),
                usage_estimated=estimated,
                failed_attempts=[] if from_cache else failures,
            )

        logger.error("all %d keys failed: %s", len(self._pool), [(f.key_id, f.status) for f in failures])
        raise AllProvidersUnavailable()

    def _request_kwargs(
        self,
        key: ApiKey,
        messages: list[dict[str, str]],
        simulated_status: int | None,
        bypass_cache_reads: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": key.model,
            "messages": messages,
            "api_key": key.secret,
            "timeout": self._timeout,
            "num_retries": 0,  # retries happen across keys here, never silently inside LiteLLM
            "caching": litellm_cache_enabled(),
        }
        if self._max_output_tokens:
            kwargs["max_tokens"] = self._max_output_tokens
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if bypass_cache_reads:
            kwargs["cache"] = {"no-cache": True}
        if simulated_status is not None:
            kwargs["mock_response"] = simulated_provider_error(simulated_status, model=key.model)
        return kwargs

    @staticmethod
    def _usage(response: Any, model: str, messages: list[dict[str, str]], text: str) -> tuple[int, int, bool]:
        """Provider-reported usage for this request; tokenizer estimate only if the provider omitted it."""
        usage = getattr(response, "usage", None)
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
        if isinstance(prompt, int) and isinstance(completion, int) and prompt > 0:
            return prompt, completion, False
        estimated_prompt = litellm.token_counter(model=model, messages=messages)
        estimated_completion = litellm.token_counter(model=model, text=text)
        return estimated_prompt, estimated_completion, True
