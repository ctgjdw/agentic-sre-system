from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

# The complete tool universe on the gateway side. Read-only by construction:
# no write-capable tool exists in this registry at all (spec section 8).
TOOL_REGISTRY: dict[str, str] = {
    "runbook_search": "semantic search over the approved-runbook index",
    "learning_search": "semantic search over distilled case learnings",
}


class AgentManifest(BaseModel):
    agent: str
    tier: Literal["small", "medium", "frontier"]
    tools: list[str] = Field(default_factory=list)
    budgets: dict = Field(default_factory=dict)


def load_manifests(dir_path: Path) -> dict[str, AgentManifest]:
    manifests: dict[str, AgentManifest] = {}
    for path in sorted(dir_path.glob("*.yaml")):
        m = AgentManifest.model_validate(yaml.safe_load(path.read_text()))
        for tool in m.tools:
            if tool not in TOOL_REGISTRY:
                raise ValueError(f"manifest {path.name}: unknown tool '{tool}' "
                                 f"(registry: {sorted(TOOL_REGISTRY)})")
        manifests[m.agent] = m
    return manifests


def assert_tool_allowed(manifests: dict[str, AgentManifest], agent: str, tool: str) -> None:
    m = manifests.get(agent)
    if m is None or tool not in m.tools:
        raise PermissionError(f"agent '{agent}' is not permitted tool '{tool}' (default-deny)")
