from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.config import Settings
from app.database import Database
from app.dependencies import get_database, get_gateway, get_settings
from app.schemas.chat import HealthResponse
from app.services.llm_gateway import LLMGateway, litellm_cache_enabled

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, responses={503: {"description": "dependency unavailable"}})
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    gateway: Annotated[LLMGateway, Depends(get_gateway)],
):
    keys_configured = len(gateway.pool)
    db_ok = await asyncio.to_thread(database.ping)
    body = {
        "keys_configured": keys_configured,
        "cache_enabled": litellm_cache_enabled(),
        "models": gateway.pool.models,
        "failure_simulation_enabled": settings.enable_failure_simulation,
        "default_system_prompt": settings.default_system_prompt,
    }
    if not db_ok or keys_configured == 0:
        reason = "database unavailable" if not db_ok else "no API keys configured"
        return JSONResponse(status_code=503, content={"status": "unavailable", "detail": reason, **body})
    return {"status": "ok", **body}
