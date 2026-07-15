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
