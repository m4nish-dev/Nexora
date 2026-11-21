"""``X-Simulate-Failure`` test hook.

Header grammar: comma-separated ``<key_id>=<status>`` pairs, ``*`` meaning every key.
Statuses: 429, 500, 502, 503. The resulting plan lives only for the request that carried it.

The plan is executed *inside* LiteLLM: the gateway passes the matching LiteLLM exception as
``mock_response`` for the targeted key, so the failure travels LiteLLM's real call path and
is handled by the same classifier as a genuine provider error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import litellm

from app.errors import InvalidSimulationHeader

SUPPORTED_STATUSES = frozenset({429, 500, 502, 503})
WILDCARD = "*"
_KEY_ID = re.compile(r"^key_[1-9]\d*$")
_MAX_HEADER_LEN = 512


@dataclass(frozen=True, slots=True)
class SimulationPlan:
    per_key: dict[str, int] = field(default_factory=dict)
    wildcard: int | None = None

    def status_for(self, key_id: str) -> int | None:
        return self.per_key.get(key_id, self.wildcard)


def parse_simulation_header(raw: str | None, *, enabled: bool) -> SimulationPlan | None:
    """Return a plan, or ``None`` when the hook is disabled or the header is absent."""
    if not enabled or raw is None or not raw.strip():
        return None
    if len(raw) > _MAX_HEADER_LEN:
        raise InvalidSimulationHeader("X-Simulate-Failure header is too long")

    per_key: dict[str, int] = {}
    wildcard: int | None = None
    for part in raw.split(","):
        target, sep, status_text = part.strip().partition("=")
        target, status_text = target.strip(), status_text.strip()
        if not sep or not target or not status_text.isdigit():
            raise InvalidSimulationHeader(
                "invalid X-Simulate-Failure header: expected comma-separated <key_id>=<status> pairs"
            )
        status = int(status_text)
        if status not in SUPPORTED_STATUSES:
            raise InvalidSimulationHeader(
                f"invalid X-Simulate-Failure status {status}: supported statuses are 429, 500, 502, 503"
            )
        if target == WILDCARD:
            wildcard = status
        elif _KEY_ID.match(target):
            per_key[target] = status
        else:
            raise InvalidSimulationHeader(f"invalid X-Simulate-Failure target {target!r}: use key_<n> or *")
    return SimulationPlan(per_key=per_key, wildcard=wildcard)


def simulated_provider_error(status: int, *, model: str) -> Exception:
    """The LiteLLM exception a provider returning ``status`` would produce."""
    provider = model.split("/", 1)[0] if "/" in model else "openai"
    message = f"simulated HTTP {status} via X-Simulate-Failure"
    if status == 429:
        return litellm.RateLimitError(message=message, llm_provider=provider, model=model)
    if status == 500:
        return litellm.InternalServerError(message=message, llm_provider=provider, model=model)
    if status == 502:
        return litellm.BadGatewayError(message=message, llm_provider=provider, model=model)
    if status == 503:
        return litellm.ServiceUnavailableError(message=message, llm_provider=provider, model=model)
    raise ValueError(f"unsupported simulated status {status}")
