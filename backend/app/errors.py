"""Domain exceptions and their JSON translations.

Contract: every error is JSON with a ``detail`` field — never a traceback or HTML page.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("nexora.errors")


class AppError(Exception):
    status_code: int = 500
    detail: str = "internal server error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.detail)
        if detail:
            self.detail = detail


class AllProvidersUnavailable(AppError):
    status_code = 503
    detail = "all providers unavailable"


class UpstreamRequestRejected(AppError):
    """The provider rejected the request itself (e.g. 400/context window); another key won't help."""

    status_code = 502
    detail = "upstream provider rejected the request"


class SessionNotFound(AppError):
    status_code = 404
    detail = "session not found"


class InvalidSimulationHeader(AppError):
    status_code = 422


class UnhandledErrorMiddleware:
    """Turn any unexpected exception into a JSON 500 *inside* CORSMiddleware.

    Starlette's catch-all ``Exception`` handler runs in the outermost middleware, i.e. outside CORS,
    so its response carries no ``Access-Control-Allow-Origin`` and the browser would report a
    network failure instead of the JSON body. Registered before CORS, this layer sits inside it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if response_started:
                raise
            response = JSONResponse(status_code=500, content={"detail": "internal server error"})
            await response(scope, receive, send)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(sqlite3.Error)
    async def _db_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
        logger.error("database error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})
