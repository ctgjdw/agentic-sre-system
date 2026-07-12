from enum import StrEnum


class CaseKind(StrEnum):
    incident = "incident"
    pipeline_failure = "pipeline_failure"


class CaseStatus(StrEnum):
    open = "open"                        # graph running or queued
    waiting_approval = "waiting_approval"  # parked at a HITL gate
    needs_human = "needs_human"          # budget breach / provider failure / manual escalate
    closed = "closed"


class SignalSource(StrEnum):
    grafana = "grafana"
    telegram = "telegram"
    chat = "chat"
    github = "github"
    gitlab = "gitlab"
    human_api = "human_api"


class FailureClass(StrEnum):
    code = "code"
    test = "test"
    config = "config"
    dependency = "dependency"
    infra_runner = "infra_runner"
    flaky = "flaky"
    permissions = "permissions"


class ArtifactKind(StrEnum):
    rca = "rca"
    runbook = "runbook"


class Decision(StrEnum):
    approve = "approve"
    approve_with_edits = "approve_with_edits"
    reject = "reject"
