import json
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_QUEUES: dict[tuple[str, str], list[Any]] = {}


def reset_scripts() -> None:
    _QUEUES.clear()


class ScriptedChatModel(BaseChatModel):
    node: str
    script_dir: Path

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        key = (str(self.script_dir), self.node)
        if key not in _QUEUES:
            path = Path(self.script_dir) / f"{self.node}.json"
            if not path.exists():
                raise FileNotFoundError(f"no script for node '{self.node}' at {path}")
            _QUEUES[key] = list(json.loads(path.read_text()))
        queue = _QUEUES[key]
        if not queue:
            raise IndexError(f"script exhausted for node '{self.node}'")
        item = queue.pop(0)
        content = item if isinstance(item, str) else json.dumps(item)
        msg = AIMessage(content=content, usage_metadata={
            "input_tokens": 50, "output_tokens": 50, "total_tokens": 100})
        return ChatResult(generations=[ChatGeneration(message=msg)])
