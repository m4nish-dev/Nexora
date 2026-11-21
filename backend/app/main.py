"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.database import Database
from app.errors import UnhandledErrorMiddleware, register_exception_handlers
from app.repositories.messages import MessageRepository
from app.routers import chat, health, sessions
from app.services.chat_service import ChatService
from app.services.key_pool import KeyPool
from app.services.llm_gateway import CompletionFn, LLMGateway, configure_litellm_cache

logger = logging.getLogger("nexora")


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # basicConfig is a no-op once another library has configured logging, so set our level explicitly.
    logging.getLogger("nexora").setLevel(level.upper())
    # LiteLLM is chatty and can include request details in debug logs; keep it at WARNING.
    for noisy in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def create_app(settings: Settings | None = None, *, completion_fn: CompletionFn | None = None) -> FastAPI:
    settings = settings or Settings()
    _configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.sqlite_path)
        database.initialize()
        cache_on = configure_litellm_cache(
            enabled=settings.cache_enabled,
            ttl_seconds=settings.cache_ttl_seconds,
            max_items=settings.cache_max_items,
        )
        pool = KeyPool.from_config(settings.api_keys, settings.key_models)
        gateway = LLMGateway(
            pool,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
            api_base=settings.llm_api_base,
            completion_fn=completion_fn,
        )
        app.state.settings = settings
        app.state.database = database
        app.state.gateway = gateway
        app.state.chat_service = ChatService(MessageRepository(database), gateway, settings.default_system_prompt)
        logger.info(
            "nexora ready db=%s keys=%d models=%s cache=%s failure_simulation=%s",
            settings.sqlite_path,
            len(pool),
            pool.models,
            cache_on,
            settings.enable_failure_simulation,
        )
        yield

    app = FastAPI(
        title="Nexora API",
        version="1.0.0",
        description="LLM chatbot with key failover and response caching (LiteLLM + SQLite).",
        lifespan=lifespan,
    )
    allow_all = settings.cors_origins == ["*"]
    # Order matters: the last middleware added is the outermost, so CORS wraps the error layer.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
        max_age=600,
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)
    return app


app = create_app()
