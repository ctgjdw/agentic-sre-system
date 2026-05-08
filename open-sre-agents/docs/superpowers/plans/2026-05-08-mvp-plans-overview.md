# OpenSRE MVP — Plans 1–4 Overview

**Source spec:** [`2026-05-08-open-sre-mvp-design.md`](../specs/2026-05-08-open-sre-mvp-design.md)
**Date:** 2026-05-08
**Purpose:** Context-management aid. Re-load this doc to recover the full mental model of the four-plan rollout when conversation context is reset.

---

## End-state success criterion (from spec §1, §11)

```
Operator: aws fis start-experiment --experiment-template-id <cpu-stress|rds-reboot>
                                ↓
            within ~3 minutes, useful RCA in the configured Telegram group:
              • alarm that fired
              • evidence (CW metrics, logs, RDS events)
              • root-cause hypothesis
              • recommended next action
            ─ same message also ingested by the OpenClaw bot in the group ─
```

---

## Plan status

| # | Plan | File | Status | Verifies |
|---|---|---|---|---|
| 1 | Foundation + SUT + UI | `2026-05-08-foundation-sut-ui.md` | ✅ Done | Posts table renders in browser; backend on `/posts` returns 1k seeded rows |
| 2 | OpenSRE host | `2026-05-08-opensre-host.md` | 📝 Drafted (9 tasks) | Synthetic alert via SSM → real RCA in Telegram group |
| 3 | Alert pipeline | `2026-05-08-alert-pipeline.md` | 📝 Drafted (7 tasks) | Manually-fired CW alarm → Lambda → SSM → host → RCA in Telegram group |
| 4 | FIS chaos + e2e | `2026-05-08-fis-chaos.md` | 📝 Drafted (6 tasks) | `start_chaos.sh cpu\|rds` → alarm → RCA in Telegram group within ~3 min |

---

## Dependency graph

```
Plan 1 (foundation) ──────► Plan 2 (host) ──────► Plan 3 (alerts) ──────► Plan 4 (chaos)
   SUT + UI + RDS              EC2 + opensre        SNS + Lambda           FIS templates
   provides target             provides agent       provides wiring        provides triggers
```

Each plan produces an independently-verifiable system. Plan N+1 depends on Plan N being applied + smoke-tested.

---

## Plan 1 — Foundation + SUT + UI ✅

**File:** `docs/superpowers/plans/2026-05-08-foundation-sut-ui.md` (1964 lines, 17 tasks)

**What it built:**
- **Backend:** FastAPI on ECS-on-EC2, `GET /health` + `GET /posts?limit=50` reading from RDS via asyncpg pool. Containerised with multi-stage Dockerfile (uv).
- **UI:** Next.js 16 (App Router, `output: 'export'`) + Tailwind v4 + shadcn/ui. Static-exported to S3 website bucket. PostsTable + Refresh button + Skeleton.
- **Data:** RDS PostgreSQL `db.t3.micro`, single-AZ, in private subnets. `posts` table seeded with 1 000 faker rows via PEP 723 inline-deps script.
- **Infra (Terraform 1.9 / AWS provider 5.x):** `infra/network.tf` (VPC, 2 public + 2 private subnets, IGW, RTs, SGs), `infra/ecr.tf`, `infra/s3.tf` (UI hosting), `infra/rds.tf`, `infra/ecs.tf` (cluster + IAM + EC2 host with EIP), `infra/ecs_service.tf` (task def + service + log group).
- **Scripts:** `scripts/seed_posts.py`, `scripts/deploy_ui.sh`.
- **Deploy pattern:** two-phase apply (`sut_desired_count = 0` → push image → seed via SSM port-forward → `sut_desired_count = 1` → deploy UI).

**Final-validation checklist passed:** UI renders posts table; `/health` returns 200; `/posts` returns 50 rows; SSM port-forward seeds RDS without exposing 5432 publicly.

**Outputs surfaced for downstream plans:**
- `sut_api_url`, `sut_instance_id`, `rds_endpoint`, `rds_address`, `ecr_repository_url`, `ui_bucket`, `ui_website_url`.

---

## Plan 2 — OpenSRE host 📝

**Target file:** `docs/superpowers/plans/2026-05-08-opensre-host.md` (planned ~9 tasks)

**Goal:** Stand up the long-lived OpenSRE EC2 that runs `opensre investigate` against synthetic alerts and posts RCAs to a Telegram group (where a downstream OpenClaw bot consumes them as input). Adds the **agent layer**; nothing yet auto-routes CW alarms here.

**New components:**
- **Secrets Manager shells:** `opensre/anthropic_api_key`, `opensre/telegram_bot_token` (created empty by Terraform; values populated manually via `aws secretsmanager put-secret-value`).
- **OpenSRE EC2:** separate `t3.micro` AL2023 in `public_a` subnet. SSM-only access (no inbound SG).
- **IAM (instance role):** `AmazonSSMManagedInstanceCore` + inline read-only AWS for investigation (`ec2:Describe*`, `ecs:Describe*`/`List*`, `rds:DescribeDBInstances`/`DescribeEvents`, `cloudwatch:GetMetricData`/`ListMetrics`, `logs:FilterLogEvents`/`GetLogEvents`, `sts:GetCallerIdentity`) + inline `secretsmanager:GetSecretValue` on the two named secrets only.
- **Bootstrap:** `opensre_host/user_data.sh.tftpl` installs OpenSRE CLI via `curl -fsSL https://install.opensre.com | bash`, fetches secrets via instance role, writes `/etc/opensre/.env` (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`, plus a `/etc/profile.d/opensre.sh` snippet so interactive shells auto-source it), runs `opensre integrations verify` (which validates Anthropic + Telegram via Telegram's `getMe` endpoint per the integration docs), and posts a "hello" sanity message via direct curl to confirm the chat ID resolves. Logs to `/var/log/opensre-bootstrap/`. **No wrapper script** — `opensre investigate` posts to Telegram natively via OpenSRE's built-in messaging integration (https://opensre.com/docs/messaging/telegram.md).
- **SSM log group:** `/aws/ssm/opensre-investigate` (7-day retention) — receives stdout/stderr from every `opensre investigate` invocation.
- **Helper script:** `scripts/test_opensre_alert.sh` — sends synthetic alert via SSM RunCommand, sources `/etc/opensre/.env`, runs `opensre investigate -i /tmp/alert-<id>.json`, polls for completion, reports status.

**New variables/outputs:**
- `var.opensre_telegram_chat_id` (numeric group chat ID like `-1001234567890`), `var.opensre_host_enabled` (toggle for two-phase apply).
- Outputs: `anthropic_secret_id`, `telegram_secret_id`, `opensre_host_instance_id`, `opensre_ssm_log_group`.

**Deploy pattern:** two-phase apply (`opensre_host_enabled = false` → populate secrets → `opensre_host_enabled = true`). Mirrors Plan 1's `sut_desired_count` toggle.

**Verification:**
1. SSM-managed-status check: `aws ssm describe-instance-information --filters "Key=InstanceIds,Values=<id>"` shows the host as Online.
2. `opensre integrations verify` via SSM RunCommand exits 0; output shows AWS + Anthropic green (Telegram is independent of OpenSRE's integration set — covered by smoke test 3 below).
3. Bootstrap "hello" message appears in the configured Telegram group.
4. `./scripts/test_opensre_alert.sh` sends a synthetic CPU-saturation alert; SSM status reaches `Success`; an RCA appears in the Telegram group; OpenClaw (if present) acknowledges receipt downstream.

**Doc verification gate:** Before Tasks 4 (user_data) and 7 (integrations verify), confirm OpenSRE CLI install URL + onboarding flags at https://www.opensre.com/docs. Telegram bot creation is via `@BotFather`; chat ID retrieval via `https://api.telegram.org/bot<TOKEN>/getUpdates`.

---

## Plan 3 — Alert pipeline 📝

**File:** `docs/superpowers/plans/2026-05-08-alert-pipeline.md` (7 tasks)

**Goal:** Wire CloudWatch alarms → SNS → Lambda → `ssm:SendCommand` invoking `opensre investigate` on the Plan-2 host. After this plan, manually setting an alarm to ALARM produces a real RCA in the Telegram group without any FIS involvement.

**New components:**
- **SNS topic** `opensre-alarms`. Lambda is the only subscription.
- **Lambda `opensre-demo-ingest-alarm`** (Python 3.12, 256 MB, 30 s timeout, zip via `archive_file`; runtime ships boto3 — no vendored deps): parses SNS payload → builds normalised alert JSON (spec §5.3) → base64-encodes → calls `ssm:SendCommand` against the OpenSRE host with `CloudWatchOutputConfig` enabled. Commands: write the alert.json from base64, source `/etc/opensre/.env` (so `TELEGRAM_BOT_TOKEN` + `TELEGRAM_DEFAULT_CHAT_ID` are in scope for OpenSRE's built-in Telegram messaging integration), then run `/usr/local/bin/opensre investigate -i /tmp/alert-<id>.json`.
- **Lambda execution role:** Basic Lambda execution + `ssm:SendCommand` scoped to the OpenSRE host instance ARN + `AWS-RunShellScript` document ARN.
- **Lambda log group** `/aws/lambda/ingest_alarm` (7-day retention).
- **CloudWatch Logs metric filter** `opensre-demo-db-connection-errors` on `/ecs/opensre-demo-sut`: pattern `?"could not connect to server" ?"connection timeout" ?"OperationalError"`. Emits `OpenSRE/SUT/DBConnectionErrors` with `default_value=0`.
- **Alarm `sut-cpu-saturation`:** `AWS/ECS CPUUtilization` (service-level) ≥ 80%, 1 datapoint / 1 min, dimensions `ClusterName=opensre-demo`, `ServiceName=opensre-demo-sut`. Action → SNS topic.
- **Alarm `sut-db-connection-errors`:** `OpenSRE/SUT/DBConnectionErrors` ≥ 1 over 1 min. Action → SNS topic.

**New code:**
- `lambda/ingest_alarm/pyproject.toml` (uv project — for tests only; runtime needs nothing)
- `lambda/ingest_alarm/src/handler.py` (only file inside the Lambda zip)
- `lambda/ingest_alarm/tests/{conftest,test_handler}.py` (4 pytest cases: SSM call shape, CPU-payload ECS resource, DB-payload RDS resource, unique invocation IDs)

**Telegram dependency:** Plan 3 contains **no Telegram-specific code**. Inherits Plan 2's `/etc/opensre/.env` and OpenSRE's built-in Telegram messaging integration end-to-end — Lambda just sources the env file and invokes `opensre investigate`, the same path proven via Plan 2's `test_opensre_alert.sh`.

**Deploy pattern:** single `terraform apply` (additive on top of Plan 2). References `aws_instance.opensre[0].id`, so requires `var.opensre_host_enabled = true`. Flipping it to `false` tears down Plan 3's Lambda automatically (intentional cost-control behaviour).

**Verification:**
1. `pytest -v` in `lambda/ingest_alarm/` — 4 tests pass.
2. `aws cloudwatch set-alarm-state --alarm-name sut-cpu-saturation --state-value ALARM …` triggers the chain; RCA arrives in Telegram within ~3 min.
3. Same for `sut-db-connection-errors`.
4. **Bonus realism check:** `aws logs put-log-events` injecting a fake `OperationalError: could not connect to server` line into `/ecs/opensre-demo-sut` causes the alarm to transition naturally (no `set-alarm-state` needed) and produce an RCA — proves the metric-filter leg of the pipeline works.

---

## Plan 4 — FIS chaos + end-to-end 📝

**File:** `docs/superpowers/plans/2026-05-08-fis-chaos.md` (6 tasks)

**Goal:** Two FIS experiment templates that, when started, produce real degradation on the SUT, fire Plan 3's alarms, and trigger Plan 2's `opensre investigate` → built-in Telegram messaging chain — meeting the spec §11 success criterion end-to-end.

**New components:**
- **FIS service role** (trust `fis.amazonaws.com`) with two inline policies:
  - For `aws:ecs:task-cpu-stress`: `ecs:DescribeTasks`/`ListTasks`/`DescribeContainerInstances`, `ec2:DescribeInstances`, `ssm:SendCommand` on `AWSFIS-Run-CPU-Stress` doc + EC2 instance ARNs in the account/region, `ssm:ListCommands`/`CancelCommand`/`GetCommandInvocation`.
  - For `aws:rds:reboot-db-instances`: `rds:RebootDBInstance`, `rds:DescribeDBInstances` on the demo RDS ARN.
- **`aws_fis_experiment_template.cpu_stress`** (`aws:ecs:task-cpu-stress`): tag-targeted (`Project=opensre-demo`, `selectionMode=ALL`); parameters `duration=PT3M`, `percent=90`, `installDependencies=True`. Stop condition: none.
- **`aws_fis_experiment_template.rds_reboot`** (`aws:rds:reboot-db-instances`): targets the demo RDS instance by ARN; parameter `forceFailover=false`. Stop condition: none.
- **Plan-1 patch:** Plan 4 modifies `infra/ecs_service.tf` to add `enable_ecs_managed_tags = true` + `propagate_tags = "SERVICE"` so the running ECS task carries `Project=opensre-demo` (required for FIS tag-based task targeting). The existing `force_new_deployment = true` causes a rolling task replacement on apply.

**New scripts:**
- `scripts/start_chaos.sh` — wrapper around `aws fis start-experiment` accepting `cpu` or `rds`; resolves the experiment-template ID via `terraform output`; optional `--follow` tails `/aws/ssm/opensre-investigate`.

**Verification (the MVP success criterion, spec §11):**
1. `./scripts/start_chaos.sh cpu` → alarm `sut-cpu-saturation` transitions OK→ALARM in 60–120 s; Lambda log shows `ssm:SendCommand sent`; SSM log shows OpenSRE stdout + Bot API `{"ok":true,...}`; RCA in Telegram within ~3 min, bracketed by `[OpenSRE RCA]` / `[OpenSRE END]`, referencing CPU saturation on `opensre-demo-sut`.
2. `./scripts/start_chaos.sh rds` (with light traffic to provoke the connection-pool failure) → alarm `sut-db-connection-errors` transitions in 90–180 s; same chain; RCA references the RDS reboot event.
3. OpenClaw bot in the same group ingests both RCAs.

**Time budget:** alarm-to-Telegram p95 ≈ 3 min (spec §5). Anthropic API latency dominates; Telegram POST adds <1 s.

**Cost:** ~$0.30 per CPU experiment (3 min × $0.10/action-min); RDS reboot is near-free. A few demo runs/month is well under $1.

---

## Cross-plan invariants

These hold across all four plans and the design enforces them:

- **No production credentials in repo.** AWS profiles + Secrets Manager only. `terraform.tfvars` is gitignored.
- **AWS Free Tier compliance** (best-effort, see spec §10). Two t3.micros at 100% uptime ≈ 1 460 h/mo > 750 h free quota; operator tears down between demos or accepts ~$8/mo overage.
- **No DLQ, no dedup, no retry infrastructure** — silent drops on persistent failure are acceptable; debug via CloudWatch Logs.
- **No DynamoDB.** OpenSRE owns its own investigation state on the EC2 host.
- **Telegram message + SSM CW Logs stream are the durable artefacts.**
- **Single account, single region** (default `us-east-1`).

---

## Apply order

Each plan must be fully applied + verified before the next one begins, because each Plan N+1 references Plan N's outputs:

```
Plan 1 apply -> seed RDS -> deploy UI       (foundation working)
   ↓
Plan 2 apply (host_enabled=false)
populate Secrets Manager (anthropic, telegram_bot_token)
Plan 2 apply (host_enabled=true) -> bootstrap "hello" in Telegram
test_opensre_alert.sh -> RCA in Telegram     (agent layer working)
   ↓
Plan 3 apply (additive)
set-alarm-state -> RCA in Telegram           (alert pipeline working)
   ↓
Plan 4 apply (additive; rolls ECS task for tags)
start_chaos.sh cpu|rds -> RCA in Telegram   (MVP success criterion ✓)
```

Toggling `var.opensre_host_enabled = false` cleanly tears down Plans 2 and 3 (the EC2 and the Lambda that depends on it) without touching Plans 1, 3 alarms/SNS, or 4 FIS templates. Re-flipping to `true` restores the agent layer.

---

## How to resume after a context reload

1. Read this doc.
2. Read the current plan file (Plan 2, 3, or 4) for task-level detail.
3. Read the spec only if the plan is ambiguous — each plan is self-contained.
4. Run `cd infra && terraform output` and `cd infra && terraform state list` to recover the actual deployed state.
5. Continue from the first unchecked `- [ ]` step in the current plan.

All four plan files are drafted and should not need re-writing unless the spec changes substantively.
