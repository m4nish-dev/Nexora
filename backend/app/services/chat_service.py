"""Chat orchestration: history → prompt → LLM gateway → atomic persistence."""

from __future__ import annotations

import asyncio
import time
import weakref
from dataclasses import asdict

from app.errors import SessionNotFound
from app.repositories.messages import MessageRepository, StoredMessage
from app.schemas.chat import ChatMetadata, ChatRequest, ChatResponse, FailedAttempt
from app.services.failure_simulation import SimulationPlan
from app.services.llm_gateway import CompletionResult, LLMGateway


class SessionLocks:
    """One asyncio.Lock per active session.

    Serialises turns of the *same* session so two concurrent requests can't both read history N
    and each append a turn built on it. Different sessions never block each other. Weak values
    let idle locks be garbage-collected, so the map can't grow without bound.
    """

    def __init__(self) -> None:
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def for_session(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock


class ChatService:
    def __init__(self, repository: MessageRepository, gateway: LLMGateway, default_system_prompt: str) -> None:
        self._repo = repository
        self._gateway = gateway
        self._default_system_prompt = default_system_prompt
        self._locks = SessionLocks()

    async def chat(
        self, request: ChatRequest, *, simulation: SimulationPlan | None, started_at: float
    ) -> ChatResponse:
        async with self._locks.for_session(request.session_id):
            history = await asyncio.to_thread(self._repo.get_history, request.session_id)
            stored_prompt = await asyncio.to_thread(self._repo.get_system_prompt, request.session_id)
            system_prompt = request.system_prompt or stored_prompt or self._default_system_prompt

            messages = build_llm_messages(system_prompt, history, request.message)
            result = await self._gateway.complete(messages, simulation=simulation)

            metadata = self._metadata(result, started_at)
            # Persisted only after a successful completion: a 422/503 never touches history.
            await asyncio.to_thread(
                self._repo.save_exchange,
                session_id=request.session_id,
                user_message=request.message,
                assistant_message=result.content,
                assistant_metadata=metadata.model_dump(),
                system_prompt=request.system_prompt,
            )
        return ChatResponse(session_id=request.session_id, reply=result.content, metadata=metadata)

    async def history(self, session_id: str) -> list[StoredMessage]:
        messages = await asyncio.to_thread(self._repo.get_history, session_id)
        if not messages:
            raise SessionNotFound()
        return messages

    @staticmethod
    def _metadata(result: CompletionResult, started_at: float) -> ChatMetadata:
        return ChatMetadata(
            resolution_source="LLM_CACHE" if result.from_cache else "LIVE_INFERENCE",
            model=result.model,
            latency_ms=max(0, round((time.perf_counter() - started_at) * 1000)),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            key_id=result.key_id,
            fallback_attempts=result.fallback_attempts,
            usage_estimated=result.usage_estimated,
            failed_attempts=[FailedAttempt(**asdict(f)) for f in result.failed_attempts],
        )


def build_llm_messages(system_prompt: str, history: list[StoredMessage], new_message: str) -> list[dict[str, str]]:
    """The exact list sent to the LLM — and therefore the cache key (with the model)."""
    return [
        {"role": "system", "content": system_prompt},
        *({"role": m.role, "content": m.content} for m in history),
        {"role": "user", "content": new_message},
    ]
