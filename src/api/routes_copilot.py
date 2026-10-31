"""Conversational copilot endpoint.

One JSON response per question rather than streaming: a call takes a few
seconds, and server-sent events would need a second client code path that the
no-LLM grounded mode could not use anyway.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from config.settings import get_settings
from src.api.security import require_api_key
from src.llm.copilot import Copilot

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


class CopilotQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(
        default=None,
        description="Continue an existing conversation. Omit to start a new one.",
    )


class ToolBreadcrumb(BaseModel):
    """What the copilot looked at, shown in the UI as it answers."""

    name: str
    arguments: dict[str, Any]
    ok: bool


class CopilotReply(BaseModel):
    session_id: str
    answer: str
    tools_used: list[ToolBreadcrumb]
    citations: list[dict[str, Any]]
    degraded: bool
    model: str


@router.post("/chat", response_model=CopilotReply, dependencies=[Depends(require_api_key)])
async def copilot_chat(payload: CopilotQuestion) -> CopilotReply:
    """Answer a question about the monitored estate, citing real telemetry."""
    copilot = Copilot(settings=get_settings())
    result = await copilot.ask(payload.question, session_id=payload.session_id)
    return CopilotReply(
        session_id=result.session_id,
        answer=result.answer,
        tools_used=[
            ToolBreadcrumb(name=record.name, arguments=record.arguments, ok=record.ok)
            for record in result.tools_used
        ],
        citations=result.citations,
        degraded=result.degraded,
        model=result.model,
    )


@router.get("/suggestions", response_model=list[str])
async def copilot_suggestions() -> list[str]:
    """Starter questions, so the UI does not hardcode them."""
    return [
        "Is everything healthy right now?",
        "Why is my application slow?",
        "What changed recently?",
        "Show me the most recent incidents",
        "Has this failure happened before?",
    ]
