from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import text

from sre_gateway.audit import get_flag
from sre_gateway.db.models import EvidenceRow
from sre_gateway.graph.deps import GraphDeps, stream_writer
from sre_gateway.llm.json_call import extract_json

SCOPES = {
    "metrics": "Use the Prometheus toolset for PromQL (rates, latencies, saturation, "
               "alert-rule state), the Tempo toolset for traces - "
               "tempo_fetch_traces_comparative_sample localizes latency by comparing "
               "fast/slow/typical traces, TraceQL search finds affected routes - and "
               "the Grafana MCP tools for dashboards and alert rules.",
    "logs": "Use the Loki toolset and elasticsearch/data (OpenSearch-compatible "
            "document/log search) to find error patterns, slow-call patterns and "
            "first-occurrence timestamps across app and audit logs.",
    "infra": "Use the Docker toolset (container state, restarts, resource stats), the "
             "Postgres toolset (DB health), and elasticsearch/cluster for search-store "
             "health: cluster status, shard allocation, node/index stats and query "
             "latency. On kubernetes/openshift platforms use the openshift/* toolsets "
             "(describe, events, logs, top).",
    "changes": "Use only GitHub / GitLab toolsets. Most incidents are change-induced: "
               "list recent commits and merged PRs/MRs, inspect diffs touching the "
               "implicated services, correlate merge times with symptom onset.",
    "ci": "Pipeline-failure investigation via GitHub / GitLab toolsets only: fetch the "
          "failed job logs with exit codes, the pipeline config (workflow YAML or "
          ".gitlab-ci.yml), the triggering diff, and the run history of the same job "
          "across recent commits and retries to detect flakiness. Set needs_infra=true "
          "only if evidence points at runners or registries.",
}


class Finding(BaseModel):
    hid: str | None = None
    direction: Literal["for", "against"] = "for"
    note: str
    evidence_idx: list[int] = Field(default_factory=list)


class FindingsOut(BaseModel):
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    proposed_hypotheses: list[str] = Field(default_factory=list)
    needs_infra: bool = False


def _board_text(hypotheses: list[dict]) -> str:
    return "\n".join(f"- {h['hid']} [{h.get('status', 'open')}] {h['statement']}"
                     for h in hypotheses) or "(no hypotheses yet)"


def make_worker(deps: GraphDeps, domain: str):
    async def worker(state: dict) -> dict:
        writer = stream_writer()
        case_id = state["case_id"]
        report = {"worker": domain, "summary": "", "findings": [],
                  "proposed_hypotheses": [], "degraded": False, "needs_infra": False}
        # Workers run outside guarded() (they're plan's fan-out, not a sequential node),
        # so without this check a case sitting at 99% budget still launches a full
        # 4-worker Holmes round before synthesize's guard ever gets a chance to park it.
        if await get_flag(deps.sessionmaker, "paused"):
            report.update(degraded=True, error="paused")
            return {"evidence": [], "worker_reports": [report]}
        breach = await deps.budget.check_case(case_id)
        if breach:
            report.update(degraded=True, error=f"budget: {breach}")
            return {"evidence": [], "worker_reports": [report]}
        try:
            ask = (
                f"Domain: {domain}\n{SCOPES[domain]}\n\n"
                f"{deps.environment.prompt_block()}\n\n"
                f"Case: {state.get('title', '')} (kind: {state.get('kind', 'incident')})\n"
                f"Hypothesis board:\n{_board_text(state.get('hypotheses', []))}\n"
                f"Operator context notes: {state.get('context_notes', [])}\n"
                f"Decisive queries from similar past cases (try these first): "
                f"{state.get('query_hints', [])}\n\n"
                "Investigate this domain. Tag every finding to a hypothesis id (hid) as "
                "for/against with evidence_idx = indexes into your own tool calls, and "
                "propose new hypotheses if the evidence suggests one."
            )

            async def on_event(event: dict) -> None:
                writer({"type": "tool_call", "worker": domain,
                        "phase": event["type"], "tool_name": event.get("tool_name", ""),
                        "toolset": event.get("toolset", ""),
                        "description": event.get("description", "")})
                if event["type"] == "tool_result":
                    await deps.audit.log_tool(case_id, worker=domain,
                                              toolset=event.get("toolset", ""),
                                              invocation=event.get("description", ""))

            tier = deps.manifests["workers"].tier
            answer = await deps.holmes.chat(
                ask, model=deps.models.holmes_model(tier),
                response_format=FindingsOut.model_json_schema(), on_event=on_event)

            # atomic evidence-id allocation across parallel workers
            n = len(answer.tool_calls)
            evidence: list[dict] = []
            if n:
                # Parse before burning counter slots: a parse failure here degrades the
                # worker (below), and doing it before the UPDATE means that degradation
                # never permanently gaps the case's eid sequence.
                out = FindingsOut.model_validate(extract_json(answer.text))
                async with deps.sessionmaker() as s:
                    start = (await s.execute(text(
                        "UPDATE cases SET evidence_counter = evidence_counter + :n "
                        "WHERE id = :id RETURNING evidence_counter"),
                        {"n": n, "id": case_id})).scalar_one() - n
                    await s.commit()
                idx_to_eid = {i: f"E{start + i + 1}" for i in range(n)}
                links: dict[str, list] = {eid: [] for eid in idx_to_eid.values()}
                findings = []
                for f in out.findings:
                    eids = [idx_to_eid[i] for i in f.evidence_idx if i in idx_to_eid]
                    findings.append({"hid": f.hid, "direction": f.direction,
                                     "note": f.note, "eids": eids})
                    for eid in eids:
                        links[eid].append({"hid": f.hid, "direction": f.direction})
                async with deps.sessionmaker() as s:
                    for i, tc in enumerate(answer.tool_calls):
                        eid = idx_to_eid[i]
                        s.add(EvidenceRow(case_id=case_id, eid=eid, worker=domain,
                                          toolset=tc.toolset or tc.tool_name,
                                          invocation=tc.invocation or tc.description,
                                          excerpt=tc.result[:2000],
                                          hypothesis_links=links[eid]))
                        evidence.append({"eid": eid, "worker": domain,
                                         "toolset": tc.toolset or tc.tool_name,
                                         "invocation": tc.invocation or tc.description,
                                         "excerpt": tc.result[:2000],
                                         "hypothesis_links": links[eid]})
                    await s.commit()
                report.update(summary=out.summary, findings=findings,
                              proposed_hypotheses=out.proposed_hypotheses,
                              needs_infra=out.needs_infra)
            else:
                out = FindingsOut.model_validate(extract_json(answer.text))
                report.update(summary=out.summary,
                              proposed_hypotheses=out.proposed_hypotheses)
                evidence = []
            return {"evidence": evidence, "worker_reports": [report]}
        except Exception as err:  # evidence-gathering degradation, never fatal (spec 10)
            report.update(degraded=True, error=str(err)[:500])
            writer({"type": "worker_warning", "worker": domain, "error": str(err)[:200]})
            await deps.audit.log("tool_call", actor=domain, case_id=case_id,
                                 degraded=True, error=str(err)[:500])
            return {"evidence": [], "worker_reports": [report]}

    return worker
