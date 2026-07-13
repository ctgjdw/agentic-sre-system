from typing import Protocol


class Channel(Protocol):
    async def send(self, text: str, *, buttons: list[dict] | None = None) -> str | None: ...
