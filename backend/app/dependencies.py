"""FastAPI dependency providers. Services are built once in the app lifespan and stored on app.state."""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.database import Database
from app.services.chat_service import ChatService
from app.services.llm_gateway import LLMGateway


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_gateway(request: Request) -> LLMGateway:
    return request.app.state.gateway


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service
