"""/api/v1/chat — sessions + SSE messages.

Auth-gated. SSE on POST /sessions/{id}/messages relays the chat orchestrator's
event stream to the frontend. Other endpoints are plain JSON.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import get_current_user
from ...models.conversation import ConversationMessage, ConversationSession
from ...models.database import get_db
from ...models.user import User
from ...services import chat as chat_service

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _envelope(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": {}}},
    )


class CreateSessionRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


def _serialize_session(s: ConversationSession) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "title": s.title,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _serialize_message(m: ConversationMessage) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "session_id": str(m.session_id),
        "role": m.role,
        "content": m.content,
        "model": m.model,
        "usage_input_tokens": m.usage_input_tokens,
        "usage_output_tokens": m.usage_output_tokens,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post(
    "/sessions", status_code=status.HTTP_201_CREATED, summary="Create a chat session"
)
async def create_session(
    body: CreateSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    session = ConversationSession(user_id=user.id, title=body.title or "New chat")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"data": _serialize_session(session)}


@router.get("/sessions", summary="List the user's chat sessions")
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.scalars(
            select(ConversationSession)
            .where(ConversationSession.user_id == user.id)
            .order_by(ConversationSession.updated_at.desc())
            .limit(100)
        )
    ).all()
    return {"data": [_serialize_session(s) for s in rows], "total": len(rows)}


@router.get(
    "/sessions/{session_id}/messages",
    summary="Get the full message history for a session",
)
async def get_messages(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    session = await db.scalar(
        select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.user_id == user.id,
        )
    )
    if session is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "session_not_found",
            f"No chat session with id {session_id}.",
        )
    rows = (
        await db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at)
        )
    ).all()
    return {"data": [_serialize_message(m) for m in rows], "total": len(rows)}


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a session (cascades to messages)",
)
async def delete_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    session = await db.scalar(
        select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.user_id == user.id,
        )
    )
    if session is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "session_not_found",
            f"No chat session with id {session_id}.",
        )
    await db.delete(session)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{session_id}/messages",
    summary="Send a user message; streams the assistant's response via SSE",
)
async def send_message(
    session_id: uuid.UUID,
    body: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    session = await db.scalar(
        select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.user_id == user.id,
        )
    )
    if session is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "session_not_found",
            f"No chat session with id {session_id}.",
        )

    async def event_stream():
        async for sse_chunk in chat_service.chat_turn(
            session=session, user=user, db=db, user_text=body.text
        ):
            yield sse_chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
