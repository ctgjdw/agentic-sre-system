import asyncio
import contextlib

import httpx
import respx

from sre_gateway.channels.telegram import TelegramChannel
from sre_gateway.settings import Settings

API = "https://api.telegram.org/bottok123"


def _channel(decisions, reports):
    async def on_decision(case_id, gate, decision, decided_by):
        decisions.append((case_id, gate, decision, decided_by))
        return "Recorded"

    async def on_report(text, reporter):
        reports.append((text, reporter))
        return "Opened CASE-0002"

    settings = Settings(database_url="x", telegram_bot_token="tok123",
                        telegram_chat_id="-10042", telegram_allowed_user_ids=[7])
    return TelegramChannel(settings, on_decision=on_decision, on_report=on_report,
                           health={})


@respx.mock
async def test_send_carries_inline_buttons():
    route = respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 5}}))
    ch = _channel([], [])
    msg_id = await ch.send("RCA ready", buttons=[
        {"text": "Approve", "data": "dec:c1:rca:approve"}])
    assert msg_id == "5"
    body = route.calls[0].request.read().decode()
    assert "inline_keyboard" in body and "dec:c1:rca:approve" in body


@respx.mock
async def test_authorized_callback_applies_decision():
    respx.post(f"{API}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    decisions, ch = [], None
    ch = _channel(decisions, [])
    await ch.handle_update({"update_id": 1, "callback_query": {
        "id": "cb1", "from": {"id": 7, "username": "alex"},
        "data": "dec:c1:rca:approve"}})
    assert decisions == [("c1", "rca", "approve", "@alex")]


@respx.mock
async def test_unauthorized_callback_is_refused():
    answered = respx.post(f"{API}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    decisions = []
    ch = _channel(decisions, [])
    await ch.handle_update({"update_id": 1, "callback_query": {
        "id": "cb1", "from": {"id": 999, "username": "mallory"},
        "data": "dec:c1:rca:approve"}})
    assert decisions == []
    assert b"authorized" in answered.calls[0].request.read().lower()


@respx.mock
async def test_dm_becomes_report_with_reply_to_dm():
    sent = respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 6}}))
    reports = []
    ch = _channel([], reports)
    await ch.handle_update({"update_id": 2, "message": {
        "chat": {"id": 4242, "type": "private"}, "from": {"id": 4242, "username": "minli"},
        "text": "admin console feels slow since noon"}})
    assert reports == [("admin console feels slow since noon", "@minli")]
    body = sent.calls[0].request.read()
    assert b"CASE-0002" in body
    # the reply goes back to the DM chat, not the configured group chat
    assert b'"chat_id": 4242' in body or b'"chat_id":4242' in body


@respx.mock
async def test_group_message_is_not_a_report():
    reports = []
    ch = _channel([], reports)
    await ch.handle_update({"update_id": 3, "message": {
        "chat": {"id": -10042, "type": "supergroup"}, "from": {"username": "minli"},
        "text": "admin console feels slow since noon"}})
    assert reports == []


@respx.mock
async def test_malformed_callback_is_answered_not_raised():
    # A malformed dec: payload (crafted via the API) must not raise a ValueError into
    # the polling loop; the button must still be answered so it stops spinning.
    answered = respx.post(f"{API}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    decisions = []
    ch = _channel(decisions, [])
    await ch.handle_update({"update_id": 1, "callback_query": {
        "id": "cb1", "from": {"id": 7, "username": "alex"}, "data": "dec:onlytwo"}})
    assert decisions == []
    assert b"nrecognized" in answered.calls[0].request.read()


@respx.mock
async def test_polling_error_never_leaks_bot_token():
    # A 401 (bad/revoked token) or any Telegram 4xx/5xx makes httpx raise an
    # HTTPStatusError whose message embeds the request URL - which carries the bot
    # token in the bot<token> path. That error is written to health["telegram"]
    # (served unauthenticated at /api/healthz) and logged, so the raw token must be
    # redacted before it escapes.
    respx.get(f"{API}/getUpdates").mock(
        return_value=httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    health: dict = {}
    settings = Settings(database_url="x", telegram_bot_token="tok123",
                        telegram_chat_id="-10042", telegram_allowed_user_ids=[7])

    async def _noop(*a, **k):
        return ""

    ch = TelegramChannel(settings, on_decision=_noop, on_report=_noop, health=health)
    task = asyncio.create_task(ch.run_polling())
    for _ in range(300):
        if "telegram" in health:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert health["telegram"].startswith("error:")
    assert "tok123" not in health["telegram"]
    assert "***" in health["telegram"]


@respx.mock
async def test_report_failure_is_contained_and_acked():
    # on_report raising (e.g. a transient DB error) must not escape handle_update (the
    # polling loop already advanced the offset, so the update is gone), must not poison
    # channel health, and the reporter must get visible feedback to retry.
    sent = respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 9}}))

    async def on_report(text, reporter):
        raise RuntimeError("db unreachable")

    async def on_decision(*a, **k):
        return ""

    settings = Settings(database_url="x", telegram_bot_token="tok123",
                        telegram_chat_id="-10042", telegram_allowed_user_ids=[7])
    health: dict = {}
    ch = TelegramChannel(settings, on_decision=on_decision, on_report=on_report,
                         health=health)
    await ch.handle_update({"update_id": 4, "message": {
        "chat": {"id": 4242, "type": "private"}, "from": {"id": 4242, "username": "minli"},
        "text": "checkout is down, 500 errors everywhere"}})
    assert "telegram" not in health  # channel health untouched by a per-message failure
    body = sent.calls[0].request.read()
    assert b"try again" in body.lower()
    assert b'"chat_id": 4242' in body or b'"chat_id":4242' in body
