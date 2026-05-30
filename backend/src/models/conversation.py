"""Conversation memory — append-only sessions + messages.

Powers the dashboard "recent chats" sidebar AND Phase B's chat history.
``content`` is JSONB with role-shaped payloads:

  user        → {"text": "..."}
  assistant   → {"text": "..."}
  tool_use    → {"tool": "...", "input": {...}, "tool_use_id": "..."}
  tool_result → {"tool_use_id": "...", "output": {...}, "is_error": false}
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        Index(
            "ix_conversation_sessions_user_updated",
            "user_id",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New chat")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index(
            "ix_conversation_messages_session_created",
            "session_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    usage_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.utcnow
    )
