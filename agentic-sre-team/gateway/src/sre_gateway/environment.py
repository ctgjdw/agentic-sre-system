from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ServiceEntry(BaseModel):
    name: str
    containers: list[str] = Field(default_factory=list)
    repo: str | None = None
    notes: str = ""


class EnvironmentConfig(BaseModel):
    """Descriptor of the environment under management (locked decision 15).

    The only place the SUT is named: prompts render from prompt_block(), so
    pointing the system at another stack is a config change, never a code change.
    """

    name: str
    description: str
    platform: Literal["docker-compose", "kubernetes", "openshift"] = "docker-compose"
    services: list[ServiceEntry] = Field(default_factory=list)

    def prompt_block(self) -> str:
        lines = [f"Target environment '{self.name}' ({self.platform}): "
                 f"{self.description}", "Services:"]
        for svc in self.services:
            repo = f" repo={svc.repo}" if svc.repo else ""
            notes = f" - {svc.notes}" if svc.notes else ""
            lines.append(f"- {svc.name} (containers: "
                         f"{', '.join(svc.containers)}){repo}{notes}")
        return "\n".join(lines)

    def all_containers(self) -> list[str]:
        return [c for svc in self.services for c in svc.containers]


def load_environment(path: Path) -> EnvironmentConfig:
    return EnvironmentConfig.model_validate(yaml.safe_load(path.read_text()))
