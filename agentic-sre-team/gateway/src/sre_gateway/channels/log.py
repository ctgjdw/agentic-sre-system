import logging

logger = logging.getLogger("sre.channel")


class LogChannel:
    """Channel adapter that only logs. Used by tests and the fake profile."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, text: str, *, buttons: list[dict] | None = None) -> str | None:
        self.sent.append({"text": text, "buttons": buttons or []})
        logger.info("channel: %s", text)
        return str(len(self.sent))
