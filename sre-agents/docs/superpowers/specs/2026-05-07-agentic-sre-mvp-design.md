# Agentic SRE MVP — Design

**Status:** Approved 2026-05-07
**Source:** Brainstorming session, 2026-05-07
**Stack:** AWS · OpenSearch · AWS FIS · Anthropic SDK (Claude Sonnet 4.6) · OpenAI SDK (gpt-5.5)

---

## 1. Goal

Build the smallest end-to-end multi-agent SRE system that proves the value loop:

> chaos event → CloudWatch alarm → agent triage → diagnosis → runbook recommendation (or proposal) → human review in Slack

The MVP must demonstrate to the organisation that combining SRE practice with agentic AI compresses incident response time. Success is measured against four FIS-validated chaos scenarios on a representative System Under Test (SUT).

### Principles (from `CLAUDE.md`)

- Human-in-the-loop on remediation. Agents recommend; humans approve.
- MVP-first. Smallest end-to-end slice.
- Reuse over rebuild — managed AWS services preferred.
- No production credentials in the repo. AWS Secrets Manager + IAM only.

---

## 2. Locked decisions

| # | Decision | Choice |
|---|---|---|
| 1 | System Under Test | 3-tier ECS Fargate web app with the existing org OpenSearch instance as data tier |
| 2 | Agent topology | Orchestrator + Triage + Diagnostician + Runbook-Matcher + Runbook-Author + 2 Codex reviewers (7 total) |
| 3 | Alert trigger | CloudWatch Alarm → SNS → Ingest Lambda |
| 4 | Runbook source | Markdown files, S3-backed corpus (seeded from repo); read at Lambda cold start |
| 5 | Diagnostician tool surface | `opensearch_search`, `cloudwatch_get_metric`, `describe_ecs_service`, `describe_ecs_tasks` |
| 6 | Review surface | Slack bot (`#sre-incidents`); reasoning trace in thread; Approve/Reject buttons |
| 7 | Approval semantics | Tracking checkbox only — no automated rectification. Proposal case has split buttons (`Approve & save` / `Approve only` / `Reject`) |
| 8 | Chaos scenarios | 4 FIS experiments: task termination, CPU stress, memory stress, simulated OS data-tier latency |
| 9 | Runtime shape | Single Ingest Lambda runs the full agent pipeline; second small Slack-callback Lambda handles button clicks |
| 10 | Reviewer model | `gpt-5.5` via OpenAI SDK; advisory, not gating |
| 11 | Specialist model | `claude-sonnet-4-6` across all five Claude roles (downshift candidates noted in §7) |

---

## 3. System architecture

```
                                    ┌──────────────────┐
   FIS Experiment ──┐                │ Runbooks (S3)    │
                    │                │ agentic-ons-     │
                    ▼                │ runbooks bucket  │
              ┌──────────┐           └────────┬─────────┘
              │   SUT    │                    │  ListObjectsV2 + GetObject
              │ ALB+ECS  │ logs+metrics       │  (cold start; cached in memory)
              │          │──────────────▶┌────▼──────────────────────┐
              └────┬─────┘               │ Ingest Lambda             │──▶ Anthropic API
                   │                     │  ┌────────────────────┐   │   (5 Claudes)
                   │ alarm metrics       │  │ Orchestrator       │   │
                   ▼                     │  │  ├─ Triage         │   │──▶ OpenAI API
              ┌──────────┐               │  │  ├─ Diagnostician  │   │   (2 reviewers, gpt-5.5)
              │CloudWatch│               │  │  │   └─ Diag-Rev*  │   │
              │  Alarms  │──▶ SNS ──────▶│  │  ├─ Runbook-Match  │───┼──▶ OpenSearch (telemetry)
              └──────────┘               │  │  └─ if low conf:   │   │
                                         │  │     Author         │   │──▶ CloudWatch (infra metrics)
                                         │  │      └─ Prop-Rev*  │   │
                                         │  └────────────────────┘   │──▶ ECS Describe API
                                         │                           │
                                         │  DynamoDB (incidents)     │──▶ Secrets Manager
                                         │                           │   (anthropic_key, openai_key)
                                         │  Slack post + thread      │
                                         └───────────────────────────┘
                                                   │
                                                   ▼
                                         ┌──────────────────────┐
                                         │ #sre-incidents       │
                                         │ [Approve] [Reject]   │ ← match case
                                         │ [Approve & save] ... │ ← proposal case
                                         └──────────┬───────────┘
                                                    │
                                                    ▼
                                         ┌──────────────────────┐
                                         │ Slack Callback       │──▶ DynamoDB (close incident)
                                         │ Lambda (API GW)      │──▶ S3 (write new runbook,
                                         └──────────────────────┘       proposal-approved case only)

* = Codex reviewer
```

### Components

| Component | Purpose |
|---|---|
| **Ingest Lambda** | Receives SNS alarm payload, runs full agent pipeline to completion, persists incident, posts Slack message. Memory 1024 MB, timeout 5 min (15 min Lambda ceiling). |
| **Slack Callback Lambda** | Receives Slack interactivity webhook via API Gateway, validates signing secret, updates incident state, conditionally writes new runbook to S3. |
| **DynamoDB `incidents`** | Source of truth. One item per alarm-triggered investigation. PK `incident_id` (UUID). Holds alarm payload, all 5–7 agent outputs, status, Slack `message_ts`. |
| **S3 `agentic-ons-runbooks`** | Runbook corpus. Key `runbooks/<slug>.md`. Slack Callback Lambda has `s3:PutObject`; Ingest Lambda has `s3:GetObject` and `s3:ListBucket` only. |
| **AWS Secrets Manager** | Holds `anthropic_api_key` and `openai_api_key`. Lambdas have `secretsmanager:GetSecretValue` on those secrets only. Cached in Lambda execution context. |
| **SQS DLQ `agentic-ons-incidents-dlq`** | Receives failed SNS deliveries (after 3 attempts) and Lambda async-invocation failures. CloudWatch alarm on depth pages on-call. |

---

## 4. Components — the seven agents

### Roster

| Agent | Role | Tools | Output contract |
|---|---|---|---|
| **Orchestrator** | Coordinates the pipeline; persists incident; posts Slack. | `delegate_to_*`, `persist_incident`, `post_slack` | Full `Incident` record |
| **Triage** | Classify alarm severity, suspected layer, affected resource. Pure prompt. | *(none)* | `{severity, suspected_layer: compute\|network\|data, affected_resource, confidence, summary}` |
| **Diagnostician** | Gather evidence, form hypothesis. Multi-step tool-use loop. | `opensearch_search`, `cloudwatch_get_metric`, `describe_ecs_service`, `describe_ecs_tasks` | `{hypothesis, evidence: [{tool, query, finding}, …], confidence, truncated?: bool}` |
| **Diagnosis-Reviewer** (Codex) | Second-perspective check on diagnosis. Advisory only. | *(none)* | `{verdict: pass\|concerns\|fail, comments: [str], suggested_rewrite?: str}` |
| **Runbook-Matcher** | Pick best-matching runbook from corpus. Corpus injected in-context. | *(none)* | `{runbook_name, match_confidence, why, alternatives_considered}` |
| **Runbook-Author** (conditional) | Fires when Matcher confidence < 0.6. Drafts a fresh runbook in corpus style. | *(none)* — corpus + diagnosis in-context | `{proposed_runbook: {name, body_markdown, applicability_signals}, rationale, novelty_score}` |
| **Proposal-Reviewer** (Codex) | Second-perspective check on proposed runbook. Advisory only. | *(none)* | Same shape as Diagnosis-Reviewer |

### Sub-agent invocation pattern

Each `delegate_to_X` tool, when called by the Orchestrator, internally spins up a fresh `messages.create()` (Anthropic) or `responses.create()` (OpenAI) loop with that specialist's system prompt, tool set, and the Orchestrator's task description. The sub-agent runs its own tool-use loop to completion or until its soft timeout, returns a structured JSON output validated against its Pydantic contract, and that result becomes the tool result handed back to the Orchestrator.

**Sub-agents do not see each other's reasoning** — only the structured output that the Orchestrator forwards. This keeps each context small, makes handoffs auditable, and prevents prompt entanglement.

### Reviewers are advisory, not gating

Reviewer verdicts surface to the human in Slack but **do not block the flow**. Rationale: the locked principle is "humans approve before any action." A second machine-gated approval layer introduces new failure modes (wrongly blocking a correct diagnosis) and contradicts the principle. Reviewer = second perspective, human still decides.

### Tool implementations (Python)

Three thin `boto3` wrappers, one OpenSearch wrapper:

- `opensearch_search(index, query_dsl, time_range)` — `opensearch-py` client with SigV4 IAM auth.
- `cloudwatch_get_metric(namespace, metric, dimensions, period, time_range)` — `boto3.client('cloudwatch').get_metric_statistics`.
- `describe_ecs_service(cluster, service)` / `describe_ecs_tasks(cluster, tasks)` — `boto3.client('ecs')`.

Each tool: strict input schema, returns shaped JSON, clamps time ranges to the alarm window ± a configurable padding, validates resource names, returns `{error: "..."}` on permanent failures rather than raising.

### Models and prompt caching

- All Claude roles: `claude-sonnet-4-6`.
- Both Codex reviewers: `gpt-5.5`.
- **Anthropic prompt caching** is on for system prompts and the runbook corpus block (the Matcher's biggest cost — corpus is static across invocations).

Downshift candidates once telemetry justifies (see §7): Triage and Matcher → `claude-haiku-4-5`. Reviewers stay on `gpt-5.5`.

---

## 5. Incident lifecycle

### End-to-end flow

```
t=0       FIS experiment fires (or real degradation begins)
t≈30s     CloudWatch alarm transitions to ALARM
          → SNS topic publishes alarm payload
          → Ingest Lambda invoked

           ┌─ Cold/warm start
           │   - load runbook corpus from S3 into memory (cold only)
           │   - parse SNS message → AlarmEvent
           │
           ├─ Idempotency check
           │   - DynamoDB conditional PutItem on (alarm_arn, alarm_state_change_time)
           │   - if duplicate: log + exit
           │
           ├─ Create Incident record (status=open)
           │
           ├─ Run orchestrator (single Claude tool-use loop)
           │   ├─ delegate_to_triage(alarm)               → triage_summary
           │   ├─ delegate_to_diagnostician(triage)       → diagnosis (multi-tool loop)
           │   ├─ delegate_to_diagnosis_reviewer(diag)    → diagnosis_review
           │   ├─ delegate_to_runbook_matcher(diagnosis)  → match_result
           │   ├─ if match_result.confidence < 0.6:
           │   │      delegate_to_runbook_author(...)     → proposal
           │   │      delegate_to_proposal_reviewer(...)  → proposal_review
           │   └─ build slack_message
           │
           ├─ Update Incident record with all agent outputs
           │
           └─ Post Slack message + threaded reasoning replies
              save slack message_ts to incident
              return

t≈30s..3min   Slack message visible in #sre-incidents

t=?       Human clicks button
          → Slack interaction webhook → API Gateway → Slack Callback Lambda
           ├─ Verify Slack signing secret
           ├─ Parse action_id (approve | approve_and_save | approve_only | reject)
           ├─ DynamoDB conditional UpdateItem on incident
           │      (status=open → terminal; sets decided_at, decided_by, runbook_promoted)
           ├─ if approve_and_save: PutObject to S3 runbooks bucket
           └─ Update original Slack message
              (replace buttons with "✅ approved by @user" or equivalent)
```

### Incident state machine

```
        ┌──────┐
        │ open │ ← created by Ingest Lambda
        └──┬───┘
           │ (Slack button click)
   ┌───────┼──────────┐
   ▼       ▼          ▼
approved  approved  rejected
(saved)   (only)
```

`open` is the only non-terminal state. Once a button is clicked, the incident is terminal — there is no "reopen." A subsequent alarm on the same resource creates a new incident.

### Slack message shapes

- **Match case** (`Matcher.confidence ≥ 0.6`):
  - Header: alarm summary
  - Diagnosis block (with `🟢 Reviewed: pass` / `🟡 concerns` / `🔴 fail`)
  - "Recommended runbook: *X* (confidence 0.82)"
  - Buttons: `[Approve]` `[Reject]`
  - Threaded replies: full reasoning trace, reviewer comments and any `suggested_rewrite`.

- **Proposal case** (`Matcher.confidence < 0.6`):
  - Header: alarm summary
  - Diagnosis block + diagnosis verdict
  - "No matching runbook found. Proposed:" + full proposed markdown in code block
  - Proposal verdict line (`🟢/🟡/🔴 Reviewed: …`)
  - Buttons: `[Approve & save]` `[Approve only]` `[Reject]`
  - Threaded replies: same as match case.

### Persistence

| Store | What | Why |
|---|---|---|
| DynamoDB `incidents` | one item per incident: alarm payload, all agent outputs, reviewer verdicts, status, message_ts | source of truth |
| S3 `agentic-ons-runbooks` | runbook markdown | corpus, growing on `Approve & save` |
| CloudWatch Logs | structured JSON per Lambda invocation | per-invocation debug |
| Slack thread | human-readable reasoning trace | demo + SRE review |

### Concurrency

- **Duplicate SNS delivery** → conditional `PutItem` rejects the second.
- **Slack button double-click** → conditional `UpdateItem` requires `status = open`; second click is a no-op.
- **Two distinct alarms on same resource** → two distinct incidents. Merging is out of scope (§7).

---

## 6. Failure modes

### Principle: failures still surface to humans

Every failure mode that prevents a clean recommendation should still produce a Slack message — never a silent drop. The human sees the alarm, sees what the system *did* manage to produce, and sees what failed.

### Failure taxonomy

| Class | Examples | Strategy |
|---|---|---|
| **Transient** | Anthropic/OpenAI rate-limit or 5xx; OpenSearch timeout; DynamoDB throttle | Up to 3 retries with exponential backoff + jitter. `boto3` provides this; LLM SDK calls wrap equivalent. |
| **Degraded but continue** | One tool fails for Diagnostician; reviewer call fails; agent hits soft timeout | Capture partial output, mark `truncated: true` or `unavailable`, continue, render warning in Slack. |
| **Permanent / hard fail** | Bad alarm payload; Slack post fails; Lambda hard timeout | DLQ via SNS redrive policy. CloudWatch alarm on DLQ depth pages on-call. |

### Soft timeouts per agent

Hard Lambda ceiling is 5 min; individual agents are cut short before that so partial results are recoverable.

| Agent | Soft cap |
|---|---|
| Triage | 30 s |
| Diagnostician | 90 s |
| Diagnosis-Reviewer | 30 s |
| Runbook-Matcher | 30 s |
| Runbook-Author | 60 s |
| Proposal-Reviewer | 30 s |

Total worst case ≈ 4.7 min, leaving Lambda headroom for I/O. Each cap is enforced via wall-clock check inside the agent's tool-use loop (`signal.alarm` is unreliable in Lambda). On cap hit: agent returns its current best-effort structured output flagged `truncated: true`, the Orchestrator logs and moves on.

### LLM-output integrity

Each agent's response is validated against its Pydantic contract. On parse failure: one corrective retry with the parser error fed back as a system message. If still malformed: agent's output recorded as `{error: "malformed_output", raw: "..."}`, flow continues, Slack message shows `⚠️ <agent> output unparseable — see thread`.

### DLQ wiring

- SNS subscription has redrive policy → SQS DLQ `agentic-ons-incidents-dlq`. After 3 SNS delivery attempts, message lands in DLQ.
- Lambda async invocation has DLQ destination on the same SQS queue.
- CloudWatch alarm on `ApproximateNumberOfMessagesVisible > 0` → SNS topic → on-call paging. Manual triage from DLQ; auto-replay deferred (§7).

### Observability

- **Structured JSON logs** per Lambda invocation, indexed fields: `incident_id`, `agent_name`, `latency_ms`, `tokens_in`, `tokens_out`, `tool_calls`, `error_type?`. CloudWatch Logs Insights queries are sufficient for debugging during the build.
- Custom metrics emission and dashboard are deferred (§7).

---

## 7. Testing — deferred

Formal test infrastructure (unit, fixture replay, reviewer calibration, automated chaos validation) is **out of scope for this MVP** due to time constraints. The four FIS chaos scenarios serve as the de facto validation path during demo: run scenario, observe Slack message, inspect DynamoDB. Add formalisation once prompt churn warrants regression nets — see §9 for the full list of items pulled from the original test plan.

---

## 8. Success metrics — goals (not implemented in MVP)

`CLAUDE.md` names MTTR and Change Failure Rate as the success metrics. CFR is hard to claim with a chaos-validated MVP (no real deployments to fail), so the framing below substitutes response-time metrics that the agents directly compress. CFR impact is secondary and qualitative.

**These metrics are documented as goalposts only.** Tracking, rollup, and dashboard implementation are deferred (§9).

| Metric | Definition | Source | Target |
|---|---|---|---|
| Time-to-Recommendation (T2R) | `agent_completed_at − alarm_state_change_time` — the agentic system's direct contribution | DynamoDB | p95 < 2 min |
| Time-to-Decision (T2D) | `decided_at − alarm_state_change_time` — includes human latency | DynamoDB | p95 < 5 min (org-dependent) |
| Recommendation Accuracy | % of incidents where the approved button was Approve (vs Reject). Binary ground truth on chaos scenarios. | DynamoDB | ≥ 80 % on chaos scenarios |
| MTTR proxy | `alarm OK transition − alarm ALARM transition` | CloudWatch alarm history | p95 < 15 min |

### Demo narrative (qualitative)

- *"Without the agent system, an on-call SRE typically spends 15–30 min triaging a novel incident before recommending a runbook."* — sourced from org incident retros (use real numbers).
- *"With the agent system, time-to-recommendation is p95 < 2 min, accuracy ≥ 80 % on validated scenarios."* — sourced from incident records once tracking is built.
- The implied **MTTR delta is the value pitch.** CFR is not directly reducible by triage tooling; we claim "blast radius of any change failure is contained faster" as a qualitative knock-on.

### Honest caveat

Recommendation Accuracy is measured against curated chaos scenarios with a fixed runbook corpus. Real-world accuracy will vary. The metric is a floor, not a ceiling.

---

## 9. Out of scope / explicit YAGNI

Each item below is deliberately deferred. The implementation plan and any v2 spec must explicitly justify pulling any of these in.

| Item | Why deferred |
|---|---|
| **Automated rectification** (rectifier Lambdas, dry-run mode) | Approval is tracking-only for MVP. Honors the "humans approve before action" principle without infra-mutation risk. |
| **Testing infrastructure** (unit, fixture replay, reviewer calibration, automated chaos validation) | Time-constrained MVP. Chaos scenarios serve as unwritten validation. Add once prompt churn warrants regression nets. |
| **Metrics rollup Lambda + EMF emission** | Goals documented in §8; no infra. Add when org wants quantitative tracking of the value loop. |
| **CloudWatch demo dashboard** (`agentic-ons-mvp`) | Same rationale as above. |
| **Custom CloudWatch metrics** for T2R / T2D / Accuracy / MTTR proxy | Same. |
| **Iterative reviewer feedback loop** | Single-pass advisory review only. Iteration adds recursion-risk and contradicts the "advisory not gating" stance. |
| **Tool-using reviewers** | Reviewers are pure-prompt for MVP. Tool access doubles complexity for marginal accuracy gain at this scale. |
| **OpenSearch / Bedrock RAG over runbooks** | Corpus is small (≤10), fits in-context. Retrieval is unnecessary plumbing. |
| **Bedrock Agents / AgentCore adoption** | Architectural lock-in we don't want before validating the value loop with our own orchestrator code. |
| **Runbook authoring via GitHub PR** | S3-backed corpus is sufficient. PR authoring adds GitHub credentials and review-cycle latency. |
| **Web UI for incident review** | Slack is the MVP review surface. UI is a v2 if Slack becomes limiting. |
| **OpenSRE / OpenClaw integration** | Wrong shape for AWS-native MVP. Both evaluated and rejected during brainstorming. |
| **Confluence / existing org runbook ingestion** | MVP corpus is curated markdown. Live Confluence sync is a v2. |
| **Cross-incident merging / dedup** | Each alarm = one incident. Merging is a v2 problem once volumes warrant it. |
| **Multi-SUT support** | One ECS Fargate demo app. Generalising across services is post-MVP. |
| **Authn/authz on Slack approvers** | Any member of `#sre-incidents` can approve. Channel membership is the access boundary. |
| **Cost optimisation / model downshift** | Sonnet/gpt-5.5 across the board. Downshift specific agents (Triage, Matcher → Haiku 4.5) once telemetry justifies. |
| **DLQ auto-replay** | DLQ alarms page on-call; replay is manual. Auto-replay needs idempotency hardening first. |
| **Combined-chaos scenarios** (CPU stress *and* OS latency simultaneously) | Adds 2nd-order failure paths. Validate single-vector first. |

---

## 10. Repo layout (target)

To be detailed in the implementation plan, but a sketch:

```
agentic-ons/
├── CLAUDE.md
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-07-agentic-sre-mvp-design.md   ← this doc
├── infra/                       # SAM or CDK templates
├── lambdas/
│   ├── ingest/                  # Ingest Lambda source
│   └── slack_callback/          # Callback Lambda source
├── agents/
│   ├── orchestrator.py
│   ├── triage.py
│   ├── diagnostician.py
│   ├── runbook_matcher.py
│   ├── runbook_author.py
│   └── reviewers/
│       ├── diagnosis_reviewer.py
│       └── proposal_reviewer.py
├── tools/
│   ├── opensearch_search.py
│   ├── cloudwatch_get_metric.py
│   └── ecs_describe.py
├── runbooks/                    # seed corpus, synced to S3 on deploy
│   ├── ecs-service-degraded.md
│   ├── ecs-task-cpu-saturation.md
│   ├── ecs-task-oom.md
│   └── data-tier-latency.md
├── chaos/                       # FIS experiment templates
│   ├── task-termination.json
│   ├── cpu-stress.json
│   ├── memory-stress.json
│   └── opensearch-latency.json
└── scripts/
    └── bootstrap-runbooks.py    # initial S3 sync
```

---

## 11. Open items for the implementation plan

- Choice of IaC tool (SAM vs CDK vs Terraform) — defer to plan.
- Lambda packaging strategy (zip vs container image) — depends on dependency size; OpenSearch SDK + boto3 + anthropic + openai may push toward a container image.
- Concrete CloudWatch alarm definitions (which metrics, thresholds, evaluation periods) for each FIS scenario — defer to plan.
- Slack app manifest (scopes, interactivity URL) — defer to plan.
- Demo SUT details (specific ALB/ECS/RDS-stand-in shape, sample workload generator) — defer to plan.

---

*End of design.*
