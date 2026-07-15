import asyncio
import contextlib
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
        self._token = settings.telegram_bot_token or ""
        self._base = f"https://api.telegram.org/bot{self._token}"

    def _redact(self, text: str) -> str:
        # httpx errors (HTTPStatusError, timeouts) embed the request URL, which carries
        # the bot token in the `bot<token>` path segment. That error text is surfaced in
        # health["telegram"] (served unauthenticated at /api/healthz) and logs, so the
        # raw token must never reach either. Strip it before it escapes this class.
        return text.replace(self._token, "***") if self._token else text

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
            # Every callback path must answer the query, or the tapped button spins on the
            # client forever. Parse defensively: a malformed `dec:` payload must produce a
            # clean answer, not a ValueError that escapes into run_polling's health/backoff.
            parts = data.split(":", 3)
            if len(parts) == 4 and parts[0] == "dec":
                _, case_id, gate, decision = parts
                try:
                    result = await self.on_decision(case_id, gate, decision, who)
                except Exception as err:
                    result = f"Failed: {self._redact(str(err))}"[:180]
            else:
                result = "Unrecognized action"
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
            # The polling loop advances the offset BEFORE calling handle_update (so a
            # poison update can't hot-loop), which means a failure here would otherwise
            # drop the report silently AND flip health["telegram"] to error for the whole
            # channel. Contain it: give the reporter visible feedback to retry, and don't
            # let a per-message failure escape into run_polling's health/backoff path.
            try:
                reply = await self.on_report(text, reporter)
                if reply:
                    await self.send(reply, chat_id=chat.get("id"))
            except Exception as err:
                logger.warning("telegram report handling failed: %s", self._redact(str(err)))
                with contextlib.suppress(Exception):
                    await self.send("Sorry, I couldn't process that just now. "
                                    "Please try again in a moment.",
                                    chat_id=chat.get("id"))

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
                safe = self._redact(str(err))
                self.health["telegram"] = f"error: {safe}"[:120]
                logger.warning("telegram polling error: %s", safe)
                await asyncio.sleep(min(backoff := backoff * 2, 60))
