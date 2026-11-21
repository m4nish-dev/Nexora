"""API key pool.

Keys are identified publicly only by their position (``key_1``, ``key_2``, ...). The secret
never leaves this object: ``repr`` hides it and ``redact`` scrubs it from any text (provider
error messages can echo request URLs, and Gemini puts the key in the query string).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

import litellm

logger = logging.getLogger("nexora.keys")


class KeyPoolConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ApiKey:
    key_id: str
    model: str
    secret: str = field(repr=False)


class KeyPool:
    def __init__(self, keys: list[ApiKey]) -> None:
        self._keys = tuple(keys)

    @classmethod
    def from_config(cls, secrets: list[str], models: list[str]) -> KeyPool:
        if len(secrets) != len(models):
            raise KeyPoolConfigError("each API key needs a model")
        for model in set(models):
            _validate_model(model)
        if len(set(secrets)) != len(secrets):
            logger.warning("LLM_API_KEYS contains duplicate keys; failover between identical keys is ineffective")
        if 0 < len(secrets) < 2:
            logger.warning("only %d API key configured; the assignment expects at least 2 for failover", len(secrets))
        return cls([ApiKey(key_id=f"key_{i}", model=m, secret=s) for i, (s, m) in enumerate(zip(secrets, models), 1)])

    def __iter__(self) -> Iterator[ApiKey]:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def models(self) -> list[str]:
        return list(dict.fromkeys(k.model for k in self._keys))

    def redact(self, text: str) -> str:
        for key in self._keys:
            if key.secret:
                text = text.replace(key.secret, f"<{key.key_id}>")
        return text


def _validate_model(model: str) -> None:
    """Fail fast at startup if LiteLLM cannot route the model to a provider."""
    try:
        litellm.get_llm_provider(model=model)
    except Exception as exc:  # LiteLLM raises a variety of types here
        raise KeyPoolConfigError(f"LiteLLM cannot resolve a provider for model {model!r}") from exc
