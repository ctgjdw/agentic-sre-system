---
title: "AI Agent Team for SRE & SysAdmin Automation"
subtitle: "Three Technology-Stack Proposals"
author: "Prepared for Alex Goh"
date: "2026-05-08"
geometry: margin=1in
fontsize: 11pt
colorlinks: true
linkcolor: NavyBlue
urlcolor: NavyBlue
toc: true
---

# AI Agent Team for SRE & SysAdmin Automation

Three concrete tech-stack proposals based on `agamm/awesome-ai-sre` plus current 2026 market research. All three reuse existing frameworks; none require building agent runtimes from scratch.

---

## Shared Agent Role Model

Use this regardless of which stack you pick.

| Role | Primary function | Allowed actions |
|---|---|---|
| **Duty Engineer** | L1 alert triage, paging, comms | Read-only on telemetry; auto-acks; routes |
| **SRE Engineer** | Investigation, RCA, hypothesis | Reads observability + runs diag commands |
| **Sys Admin** | OS patching, config drift, capacity | Stages patches, opens CRs, executes after approval |
| **Security Engineer** | CVE triage, exploitability, mitigation | Proposes patches/WAF rules; HITL gate for prod |
| **Compliance Officer** | SOC2/ISO/CIS evidence, policy attestation | Read-only; writes evidence + reports |
| **Change Manager** *(human-required)* | Approves prod changes | The HITL gate |
| **Postmortem Writer** | Incident summary, action items | Writes docs only |

**Architecture pattern:** AI proposes -> human approves -> AI executes. A centralised orchestrator (supervisor) consistently outperforms decentralised swarms in 2026 research.

---

## Proposal A — Open-Source Self-Hosted ("the FOSS stack")

**Best for:** privacy-sensitive orgs, on-prem deployments, regulated industries.

| Layer | Tool | Why |
|---|---|---|
| Team mgmt UI | **Multica** | Linear-style assignee/issue model; agents are teammates. Works with Claude Code, Codex, Gemini, Cursor, etc. |
| Orchestration | **LangGraph** | Native HITL pause/resume; durable state; deterministic execution — only major framework with first-class human approval gates |
| Investigation agent | **HolmesGPT** (CNCF Sandbox) | ReAct-pattern Kubernetes/cloud investigator; MCP-extensible; bring-your-own-model |
| K8s diagnostics | **K8sGPT** (CNCF) | Lightweight cluster scanner |
| Runbook execution | **StackStorm** | 6000+ actions, event-driven, used in production by Netflix |
| Patching | **Ansible Lightspeed** + **OpenAI Aardvark** | Lightspeed for OS playbooks; Aardvark for code-level CVE patches |
| Compliance | **Comp AI** (open-source) | Continuous endpoint agent for SOC2/CIS evidence; natural-language test generation |
| Observability | **Grafana stack** (Loki / Tempo / Mimir) + Grafana Assistant, or **SigNoz** | Open-source; OTel-native |
| Protocols | **MCP** for tools, **A2A** for inter-agent | Multica + HolmesGPT both speak MCP |

---

## Proposal B — Commercial / Managed ("the enterprise stack")

**Best for:** orgs that want vendor support, faster time-to-value, and have budget.

| Layer | Tool | Why |
|---|---|---|
| Team mgmt UI | **Paperclip** | Org-chart + budget governance + per-agent spend caps — better fit when AI labor is treated as a cost center |
| Orchestration | **CrewAI** | Role / goal / backstory abstraction maps cleanly to job titles; fastest to assemble; A2A support |
| SRE Agent | **Azure SRE Agent** (GA) | Policy guardrails, no-code workflow builder, restart / scale / rollback with mandatory approval |
| Sys admin / patching | **Tenable Hexa AI** custom agents | MCP-based orchestration; built for vulnerability remediation at machine speed |
| Security validation | **Qualys Agent Val** | TruConfirm exploitability proof + virtual patches / WAF / network containment as bridges to real patches |
| Compliance | **Delve** or **EasyAudit** | Auto-screenshot evidence, pre-mapped controls for SOC2 / ISO27001 / HIPAA |
| Incident mgmt | **incident.io** or **Rootly** | Slack-native, AI postmortems |
| Observability | **Datadog Bits AI** or **Dynatrace Davis** | Mature AIOps; runbook-aware |
| ChatOps | Claude Code / Codex via Multica or Paperclip workers | Coding role for code-level fixes |

---

## Proposal C — Hybrid Pragmatic ("recommended starting point")

Mix open-source where flexibility matters, commercial where reliability matters.

```
            +------------------------------------------+
            |  Multica  (assignee/issue UI for humans) |
            +-----------------------+------------------+
                                    |
            +-----------------------v------------------+
            | LangGraph supervisor (HITL gates)        |
            |   |- CrewAI sub-crew for research        |
            +-+-------+-------+-------+-------+--------+
              |       |       |       |       |
        Duty Eng    SRE   SysAdmin   Sec   Compliance
              |       |       |       |       |
        PagerDuty Holmes  Ansible Aardvark  Comp AI
        + Slack    GPT  Lightspeed +Qualys  + Delve
              |       |       |       |       |
              +-------+-------+-------+-------+
                         MCP tool layer
              (Prometheus, Loki, GitHub, Jira, ITSM)
```

### Why this combo

- **Multica** as the human-facing surface — engineers already think in tickets.
- **LangGraph** as the supervisor (state, persistence, HITL) — solves the "agent sprawl" reliability problem flagged in Datadog's 2026 *State of AI Engineering*.
- **CrewAI** for the parallel research phase only (cheap, fast multi-perspective brainstorming), then handoff to LangGraph for execution. This is the documented hybrid pattern used in production.
- **HolmesGPT** for live investigation — actively maintained, CNCF-backed, MCP-extensible.
- **Ansible Lightspeed + Aardvark + Qualys Agent Val** covers the patching pipeline end-to-end (code -> OS -> runtime mitigation).
- **Comp AI + Delve** splits continuous monitoring from audit-ready reporting.

---

## Cross-Cutting Concerns

Don't skip these:

1. **HITL gates are non-negotiable for prod actions.** Bake approval into the LangGraph state machine, not bolt it on.
2. **Runbooks > model selection.** Production case studies (STCLab, others) found runbook quality determined investigation quality far more than which LLM was used.
3. **Budget caps per agent.** Both Paperclip and Multica support this — turn it on day one. AutoGen-style unbounded loops can rack up four-figure bills.
4. **AIBOM + audit trails.** Track which model + framework + tool version was used for every action. SOC2 CC8.1 now requires this for AI-mediated changes.
5. **Avoid AutoGen for new builds.** Microsoft put it in maintenance mode; use the broader Microsoft Agent Framework or one of the above instead.
6. **Start narrow.** Recommended ramp: read-only investigation -> low-risk PR auto-merge for minor CVEs -> reboot / scale with approval -> broader remediation.

---

## Recommendation

Start with **Proposal C**. Specifically:

1. Stand up **Multica** as the front door (Week 1–2).
2. Wire **HolmesGPT + Comp AI** as read-only agents first (Week 2–4).
3. Add **LangGraph supervisor** with HITL approval gates (Week 4–6).
4. Layer **Ansible Lightspeed + Aardvark** for patching with mandatory human approval (Week 6–10).
5. Only then enable autonomous low-risk actions (minor-version PR merges, restart-on-OOM).

This avoids vendor lock-in, leverages CNCF-graded components, and matches the supervisor + specialists architecture that 2026 research consistently shows outperforms decentralised swarms.

---

## Sources

- [agamm/awesome-ai-sre](https://github.com/agamm/awesome-ai-sre)
- [Paperclip](https://paperclip.ing/) · [paperclipai/paperclip GitHub](https://github.com/paperclipai/paperclip)
- [multica-ai/multica GitHub](https://github.com/multica-ai/multica)
- [HolmesGPT GitHub](https://github.com/HolmesGPT/holmesgpt) · [HolmesGPT on CNCF](https://www.cncf.io/blog/2026/01/07/holmesgpt-agentic-troubleshooting-built-for-the-cloud-native-era/)
- [CrewAI vs LangGraph vs AutoGen — DataCamp](https://www.datacamp.com/tutorial/crewai-vs-langgraph-vs-autogen)
- [LangGraph vs CrewAI vs AutoGen 2026 — Pratik Pathak](https://pratikpathak.com/langgraph-vs-crewai-vs-autogen-2026/)
- [Best Multi-Agent Frameworks 2026 — Gurusup](https://gurusup.com/blog/best-multi-agent-frameworks-2026)
- [Azure SRE Agent](https://azure.microsoft.com/en-us/products/sre-agent)
- [What Is an AI SRE Agent? — Rootly](https://rootly.com/sre/ai-sre-agent-ai-changing-incident-response-2026)
- [Top 14 AI SRE Tools in 2026 — Sherlocks](https://www.sherlocks.ai/blog/top-ai-sre-tools-in-2026)
- [Top 20 AI SRE Tools — Neubird](https://neubird.ai/blog/top-ai-sre-tools/)
- [Agent Sprawl — Datadog State of AI Eng 2026 response](https://dev.to/ajaydevineni/agent-sprawl-is-your-next-production-incident-an-sre-response-to-datadogs-state-of-ai-engineering-3k83)
- [OpenAI Aardvark](https://openai.com/index/introducing-aardvark/)
- [Tenable Hexa AI custom agents](https://securityboulevard.com/2026/04/beating-the-mythos-clock-using-tenable-hexa-ai-custom-agents-for-automated-patching/)
- [Qualys Agent Val](https://blog.qualys.com/product-tech/2026/03/23/meet-agent-val-closing-the-validation-gap-in-exposure-management-at-machine-speed-with-agentic-ai)
- [AI Vulnerability Remediation tools 2026 — CodeBrewTools](https://codebrewtools.com/blogs/ai-vulnerability-remediation-auto-patching-tools)
- [Comp AI](https://www.trycomp.ai/) · [Delve](https://delve.co/) · [EasyAudit](https://www.easyaudit.ai/)
- [How AI Agents Impact SOC 2 — Teleport](https://goteleport.com/blog/ai-agents-soc-2/)
- [Agentic AI Compliance — Aisera](https://aisera.com/blog/agentic-ai-compliance/)
