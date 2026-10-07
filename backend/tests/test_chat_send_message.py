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
        self.rollbacks = 0

    async def scalar(self, _stmt):
        return self._session

    def add(self, obj):
        self.added.append(obj)

    async def rollback(self):
        self.rollbacks += 1

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


def test_user_message_is_saved_before_the_response_is_returned(monkeypatch):
    async def idle_turn(**_kwargs):
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_service, "chat_turn", idle_turn)
    session = new_session()
    db = DB(session)

    async def go():
        await chat_api.send_message(session.id, body("saved first"), USER, db)
        return db.commits, [m.content for m in db.added]

    commits, saved = run(go())
    assert commits == 1
    assert saved == [{"text": "saved first"}]


def test_long_first_message_becomes_a_60_character_title():
    session = new_session()
    run(
        chat_service.persist_user_message(
            session=session, db=DB(None), user_text="x" * 200
        )
    )
    assert session.title == "x" * 60


def test_unknown_session_error_body_uses_the_standard_envelope():
    with pytest.raises(chat_api.HTTPException) as exc:
        run(chat_api.send_message(uuid.uuid4(), body(), USER, DB(None)))
    assert exc.value.detail["error"]["code"] == "session_not_found"


def test_mid_stream_failure_rolls_back_the_session(monkeypatch):
    async def exploding_turn(**_kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_service, "chat_turn", exploding_turn)
    session = new_session()
    db = DB(session)

    async def go():
        response = await chat_api.send_message(session.id, body(), USER, db)
        return await collect(response)

    run(go())
    assert db.rollbacks == 1


# ── real chat_turn, with the model and history stubbed ──────────────


def stub_turn_dependencies(monkeypatch, events):
    async def history(_db, _session_id):
        return []

    async def classify(_text, _history):
        return "general"

    async def stream(**_kwargs):
        for event in events:
            yield event

    monkeypatch.setattr(chat_service, "_load_session_history", history)
    monkeypatch.setattr(chat_service.intent_classifier, "classify", classify)
    monkeypatch.setattr(chat_service.ai, "stream", stream)


def collect_turn(session, db, **kwargs):
    async def go():
        return [
            c
            async for c in chat_service.chat_turn(
                session=session, user=USER, db=db, user_text="hi", **kwargs
            )
        ]

    return run(go())


def test_chat_turn_skips_saving_when_the_route_already_saved(monkeypatch):
    stub_turn_dependencies(monkeypatch, [("delta", "ok")])
    session, db = new_session(), DB(None)
    collect_turn(session, db, user_message_persisted=True)
    roles = [m.role for m in db.added]
    assert roles == ["assistant"]


def test_chat_turn_saves_the_user_message_itself_by_default(monkeypatch):
    stub_turn_dependencies(monkeypatch, [("delta", "ok")])
    session, db = new_session(), DB(None)
    collect_turn(session, db)
    assert [m.role for m in db.added] == ["user", "assistant"]


def test_chat_turn_streams_intent_deltas_and_done_and_saves_the_reply(monkeypatch):
    usage = {"input_tokens": 3, "output_tokens": 5}
    stub_turn_dependencies(
        monkeypatch,
        [("delta", "Hel"), ("delta", "lo"), ("usage", usage), ("done", None)],
    )
    session, db = new_session(), DB(None)
    chunks = collect_turn(session, db, user_message_persisted=True)
    payloads = [c.removeprefix("data: ").strip() for c in chunks]
    assert json.loads(payloads[0]) == {"intent": "general"}
    assert [json.loads(p)["delta"] for p in payloads[1:3]] == ["Hel", "lo"]
    assert payloads[-1] == "[DONE]"
    reply = db.added[-1]
    assert reply.role == "assistant" and reply.content == {"text": "Hello"}
    assert reply.usage_input_tokens == 3 and reply.usage_output_tokens == 5


def test_chat_turn_saves_partial_text_when_the_client_disconnects(monkeypatch):
    stub_turn_dependencies(monkeypatch, [("delta", "part"), ("delta", "ial")])
    session, db = new_session(), DB(None)

    async def go():
        gen = chat_service.chat_turn(
            session=session,
            user=USER,
            db=db,
            user_text="hi",
            user_message_persisted=True,
        )
        await gen.__anext__()  # intent
        await gen.__anext__()  # first delta
        await gen.aclose()  # client drops: GeneratorExit

    run(go())
    saved = db.added[-1]
    assert saved.content == {"text": "part", "_partial": True}


def test_disconnect_on_the_final_event_does_not_save_the_reply_twice(monkeypatch):
    stub_turn_dependencies(monkeypatch, [("delta", "done text")])
    session, db = new_session(), DB(None)

    async def go():
        gen = chat_service.chat_turn(
            session=session,
            user=USER,
            db=db,
            user_text="hi",
            user_message_persisted=True,
        )
        await gen.__anext__()  # intent
        await gen.__anext__()  # delta
        await gen.__anext__()  # [DONE], reply already committed
        await gen.aclose()

    run(go())
    assert [m.content for m in db.added] == [{"text": "done text"}]
