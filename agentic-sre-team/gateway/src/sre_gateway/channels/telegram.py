import asyncio
import logging
from typing import Awaitable, Callable

import httpx

from sre_gateway.settings import Settings

logger = logging.getLogger("sre.telegram")

OnDecision = Callable[[str, str, str, str], Awaitable[str]]
OnReport = Callable[[str, str], Awaitable[str]]


class TelegramChannel:
    def __init__(self, settings: Settings, *, on_decision: OnDecision,
                 on_report: OnReport, health: dict) -> None:
        self.settings = settings
        self.on_decision = on_decision
        self.on_report = on_report
        self.health = health
        self._base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    async def send(self, text: str, *, buttons: list[dict] | None = None,
                   chat_id: str | int | None = None) -> str | None:
        payload: dict = {"chat_id": chat_id or self.settings.telegram_chat_id,
                         "text": text[:4000]}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[
                {"text": b["text"], "callback_data": b["data"][:64]} for b in buttons]]}
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(f"{self._base}/sendMessage", json=payload)
            res.raise_for_status()
            return str(res.json().get("result", {}).get("message_id", ""))

    async def _answer(self, callback_id: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            await client.post(f"{self._base}/answerCallbackQuery",
                              json={"callback_query_id": callback_id, "text": text[:200]})

    async def handle_update(self, update: dict) -> None:
        if cq := update.get("callback_query"):
            user = cq.get("from", {})
            who = f"@{user.get('username')}" if user.get("username") else str(user.get("id"))
            data = cq.get("data", "")
            if user.get("id") not in self.settings.telegram_allowed_user_ids:
                await self._answer(cq["id"], "Not authorized to decide gates")
                return
            if data.startswith("dec:"):
                _, case_id, gate, decision = data.split(":", 3)
                try:
                    result = await self.on_decision(case_id, gate, decision, who)
                except Exception as err:
                    result = f"Failed: {err}"[:180]
                await self._answer(cq["id"], result)
            return
        message = update.get("message") or {}
        text = message.get("text", "")
        chat = message.get("chat", {})
        # Report intake is DM-only: a private chat with the bot. Group messages
        # (the notification + approval surface) are ignored for intake, which also
        # means Bot API privacy mode never blocks us - DMs are always delivered.
        if text and chat.get("type") == "private":
            frm = message.get("from", {})
            reporter = f"@{frm['username']}" if frm.get("username") else str(frm.get("id"))
            reply = await self.on_report(text, reporter)
            if reply:
                await self.send(reply, chat_id=chat.get("id"))

    async def run_polling(self) -> None:
        offset: int | None = None
        backoff = 1
        while True:
            try:
                params: dict = {"timeout": 50}
                if offset is not None:
                    params["offset"] = offset
                async with httpx.AsyncClient(timeout=60) as client:
                    res = await client.get(f"{self._base}/getUpdates", params=params)
                    res.raise_for_status()
                for update in res.json().get("result", []):
                    offset = update["update_id"] + 1
                    await self.handle_update(update)
                self.health["telegram"] = "ok"
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.health["telegram"] = f"error: {err}"[:120]
                logger.warning("telegram polling error: %s", err)
                await asyncio.sleep(min(backoff := backoff * 2, 60))
