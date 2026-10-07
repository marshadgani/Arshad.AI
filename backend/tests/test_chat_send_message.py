"""A database failure while saving the user's message must be a real error
status, not a silently truncated 200 stream (FEAT-163)."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from src.api.v1 import chat as chat_api
from src.services import chat as chat_service

USER = SimpleNamespace(id=uuid.uuid4())


class DB:
    def __init__(self, session):
        self._session = session
        self.added = []
        self.commits = 0
        self.fail_commit = False

    async def scalar(self, _stmt):
        return self._session

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("db down")
        self.commits += 1


def new_session(title="New chat"):
    return SimpleNamespace(id=uuid.uuid4(), title=title, updated_at=None)


def body(text="hello"):
    return chat_api.SendMessageRequest(text=text)


def run(coro):
    return asyncio.run(coro)


async def collect(response):
    return [chunk async for chunk in response.body_iterator]


def test_persist_saves_message_and_sets_title():
    session, db = new_session(), DB(None)
    run(chat_service.persist_user_message(session=session, db=db, user_text="hi there"))
    assert db.commits == 1
    assert db.added[0].role == "user" and db.added[0].content == {"text": "hi there"}
    assert session.title == "hi there"
    assert session.updated_at is not None


def test_persist_keeps_existing_title():
    session = new_session(title="Kept")
    run(chat_service.persist_user_message(session=session, db=DB(None), user_text="x"))
    assert session.title == "Kept"


def test_db_failure_before_streaming_raises_instead_of_returning_a_stream():
    session = new_session()
    db = DB(session)
    db.fail_commit = True
    with pytest.raises(RuntimeError, match="db down"):
        run(chat_api.send_message(session.id, body(), USER, db))


def test_unknown_session_is_404():
    db = DB(None)
    with pytest.raises(chat_api.HTTPException) as exc:
        run(chat_api.send_message(uuid.uuid4(), body(), USER, db))
    assert exc.value.status_code == 404


def test_stream_passes_chunks_through_and_marks_user_message_persisted(monkeypatch):
    seen = {}

    async def fake_turn(**kwargs):
        seen.update(kwargs)
        yield 'data: {"delta": "a"}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_service, "chat_turn", fake_turn)
    session = new_session()
    db = DB(session)

    async def go():
        response = await chat_api.send_message(session.id, body("q"), USER, db)
        return response, await collect(response)

    response, chunks = run(go())
    assert response.media_type == "text/event-stream"
    assert chunks == ['data: {"delta": "a"}\n\n', "data: [DONE]\n\n"]
    assert seen["user_message_persisted"] is True
    assert db.commits == 1


def test_mid_stream_failure_emits_error_event_then_done(monkeypatch):
    async def exploding_turn(**_kwargs):
        yield 'data: {"delta": "partial"}\n\n'
        raise RuntimeError("model blew up")

    monkeypatch.setattr(chat_service, "chat_turn", exploding_turn)
    session = new_session()

    async def go():
        response = await chat_api.send_message(session.id, body(), USER, DB(session))
        return await collect(response)

    chunks = run(go())
    assert chunks[0] == 'data: {"delta": "partial"}\n\n'
    error = json.loads(chunks[1].removeprefix("data: "))
    assert error["error"]["code"] == "stream_failed"
    assert "model blew up" not in chunks[1]
    assert chunks[-1] == "data: [DONE]\n\n"


def test_chat_turn_still_persists_for_other_callers(monkeypatch):
    calls = []

    async def fake_persist(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(chat_service, "persist_user_message", fake_persist)

    async def go():
        async for _ in chat_service.chat_turn(
            session=new_session(), user=USER, db=DB(None), user_text="x"
        ):
            pass

    with pytest.raises(RuntimeError, match="stop here"):
        run(go())
    assert len(calls) == 1
