from pydantic import BaseModel, Field
from sqlalchemy import func, select

from sre_gateway.db.models import Artifact, EvidenceRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json

SYSTEM = (
    "You are the remediation drafter. Draft a runbook for the approved RCA: pre-checks, "
    "steps (commands, config diffs), post-checks, rollback plan, risk notes. You NEVER "
    "execute anything; you only draft. For pipeline-failure cases include patch_files: "
    "the complete corrected content of each file to change (workflow YAML, "
    ".gitlab-ci.yml, or source files)."
)


class RunbookStep(BaseModel):
    title: str
    detail: str = ""
    command: str | None = None


class PatchFile(BaseModel):
    path: str
    content: str


class RunbookOut(BaseModel):
    pre_checks: list[str] = Field(default_factory=list)
    steps: list[RunbookStep] = Field(default_factory=list)
    post_checks: list[str] = Field(default_factory=list)
    rollback: list[str] = Field(default_factory=list)
    risk_notes_md: str = ""
    patch_files: list[PatchFile] | None = None


def render_runbook_md(out: RunbookOut) -> str:
    lines = ["## Pre-checks"] + [f"- {x}" for x in out.pre_checks] + ["", "## Steps"]
    for i, s in enumerate(out.steps, 1):
        lines.append(f"{i}. **{s.title}** - {s.detail}")
        if s.command:
            lines += ["```", s.command, "```"]
    lines += ["", "## Post-checks"] + [f"- {x}" for x in out.post_checks]
    lines += ["", "## Rollback"] + [f"- {x}" for x in out.rollback]
    lines += ["", "## Risk notes", out.risk_notes_md]
    if out.patch_files:
        lines += ["", "## Patch"]
        for p in out.patch_files:
            lines += [f"### `{p.path}`", "```", p.content, "```"]
    return "\n".join(lines)


def make_remediate(deps: GraphDeps):
    async def remediate(state: dict) -> dict:
        case_id = state["case_id"]
        async with deps.sessionmaker() as s:
            rca_art = await s.get(Artifact, state["rca"]["artifact_id"])
            evidence = (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id)
                .order_by(EvidenceRow.eid))).scalars().all()
            prev = (await s.execute(
                select(func.max(Artifact.version)).where(Artifact.case_id == case_id,
                                                         Artifact.kind == "runbook"))
                    ).scalar_one() or 0
        rca_body = rca_art.body_edited_md or rca_art.body_md

        tier = deps.manifests["remediate"].tier
        model_id, pricing = deps.models.describe(tier)
        user = (f"Case: {state.get('title', '')} (kind {state.get('kind', 'incident')}, "
                f"failure_class {state.get('failure_class')}).\n"
                f"Approved RCA:\n{rca_body}\n\nEvidence index:\n" +
                "\n".join(f"- {e.eid} [{e.toolset}] {e.excerpt[:200]}" for e in evidence) +
                f"\nReviewer notes: {state.get('context_notes', [])}\n"
                + ("This is a pipeline-failure case: patch_files is REQUIRED."
                   if state.get("kind") == "pipeline_failure" else ""))
        out = await call_llm_json(deps.models.chat(tier, "remediate"), system=SYSTEM,
                                  user=user, schema=RunbookOut, audit=deps.audit,
                                  node="remediate", case_id=case_id,
                                  model_id=model_id, pricing=pricing)

        async with deps.sessionmaker() as s:
            art = Artifact(case_id=case_id, kind="runbook", version=prev + 1,
                           structured=out.model_dump(), body_md=render_runbook_md(out),
                           model_id=model_id)
            s.add(art)
            await s.commit()
            artifact_id = art.id
        return {"runbook": {"artifact_id": artifact_id, "version": prev + 1,
                            "structured": out.model_dump()}}

    return remediate
