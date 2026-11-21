from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.config import Settings
from app.dependencies import get_chat_service, get_settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.failure_simulation import parse_simulation_header

router = APIRouter(tags=["chat"])

_ERRORS = {
    422: {"description": "Validation error or malformed X-Simulate-Failure header"},
    502: {"description": "Provider rejected the request itself"},
    503: {"description": "all providers unavailable"},
}


@router.post("/chat", response_model=ChatResponse, responses=_ERRORS)
async def chat(
    body: ChatRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    x_simulate_failure: Annotated[str | None, Header(alias="X-Simulate-Failure")] = None,
) -> ChatResponse:
    started_at = time.perf_counter()
    simulation = parse_simulation_header(x_simulate_failure, enabled=settings.enable_failure_simulation)
    return await service.chat(body, simulation=simulation, started_at=started_at)
