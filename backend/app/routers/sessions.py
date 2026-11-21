from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.dependencies import get_chat_service
from app.schemas.chat import HistoryMessage, SessionHistoryResponse
from app.services.chat_service import ChatService

router = APIRouter(tags=["sessions"])


@router.get(
    "/sessions/{session_id}/messages",
    response_model=SessionHistoryResponse,
    response_model_exclude_unset=True,  # user turns carry no metadata key, matching the contract example
    responses={404: {"description": "session not found"}},
)
async def session_messages(
    session_id: Annotated[str, Path(min_length=1, max_length=128)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> SessionHistoryResponse:
    stored = await service.history(session_id)
    messages = [
        HistoryMessage(role=m.role, content=m.content, metadata=m.metadata, created_at=m.created_at)
        if m.role == "assistant"
        else HistoryMessage(role=m.role, content=m.content, created_at=m.created_at)
        for m in stored
    ]
    return SessionHistoryResponse(session_id=session_id, messages=messages)
