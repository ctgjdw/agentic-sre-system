# OpenSRE MVP — Plans 1–5 Overview

**Source spec:** [`2026-05-08-open-sre-mvp-design.md`](../specs/2026-05-08-open-sre-mvp-design.md) (revised 2026-05-09 — see §0 of the spec)
**Date:** 2026-05-08, revised 2026-05-09 (CPU chaos surface switched from `aws:ecs:task-cpu-stress` to a load-driven burst; added Plan 4 to prepare the SUT + OpenSRE host for realistic load)
**Purpose:** Context-management aid. Re-load this doc to recover the full mental model of the five-plan rollout when conversation context is reset.

---

## End-state success criterion (from spec §1, §11)

```
Operator: aws fis start-experiment --experiment-template-id <cpu-load-burst|rds-reboot>
                                ↓
            within ~3 minutes, useful RCA in the configured Telegram group:
              • alarm that fired
              • evidence (CW metrics, access logs with varied source IPs +
                weighted endpoint mix, RDS events)
              • root-cause hypothesis
              • recommended next action
            ─ same message also ingested by the OpenClaw bot in the group ─
```

---

## Plan status

| # | Plan | File | Status | Verifies |
|---|---|---|---|---|
| 1 | Foundation + SUT + UI | `2026-05-08-foundation-sut-ui.md` | ✅ Done | Posts table renders in browser; backend on `/posts` returns 1k seeded rows |
| 2 | OpenSRE host | `2026-05-08-opensre-host.md` | ✅ Done | Synthetic alert via SSM → real RCA in Telegram group |
| 3 | Alert pipeline | `2026-05-08-alert-pipeline.md` | ✅ Done | Manually-fired CW alarm → Lambda → SSM → host → RCA in Telegram group |
| 4 | Realistic-load preparation | `2026-05-09-realistic-load.md` | ✅ Done | SUT API expanded; `load_runner.py` on the OpenSRE host drives 50-VU burst with varied `203.0.113.X` IPs into `/ecs/...` log group; CPU climbs ≥ 50 % |
| 5 | FIS chaos + e2e | `2026-05-08-fis-chaos.md` | 📝 Drafted (5 tasks) | `start_chaos.sh cpu\|rds` → realistic load (or RDS reboot) → alarm → RCA in Telegram group within ~3 min |

---

## Dependency graph

```
Plan 1 ──► Plan 2 ──► Plan 3 ──► Plan 4 ──────────────► Plan 5
foundation host       alerts    SUT API + load_runner    FIS templates
SUT+UI+RDS opensre    SNS+λ     installs on host         drive cpu-load-burst
                                + 10k rows + indices     + rds-reboot
```

Each plan produces an independently-verifiable system. Plan N+1 depends on Plan N being applied + smoke-tested. Plan 4 is the **prerequisite** for Plan 5's `cpu-load-burst` template — without it, `load_runner.py` doesn't exist on the host.

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

## Plan 2 — OpenSRE host ✅

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

## Plan 3 — Alert pipeline ✅

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

## Plan 4 — Realistic-load preparation ✅

**File:** `docs/superpowers/plans/2026-05-09-realistic-load.md` (12 tasks)

**Goal:** Prepare the SUT and the OpenSRE host so Plan 5's `cpu-load-burst` FIS template can drive realistic, multi-endpoint REST traffic that produces access-log evidence the agent can correlate with CPU saturation. Without this plan, the synthetic in-task `aws:ecs:task-cpu-stress` would saturate CPU but leave the access log silent — the agent then concludes *"CPU is high but I can't see why"* (the unsatisfying RCA observed in the 2026-05-09 smoke test). Plan 4 makes the cause/effect visible in the log group OpenSRE reads.

**New components:**
- **SUT API expansion:** four new FastAPI handlers (`GET /posts/{id}`, `GET /posts/search?q=…` with non-indexed `ILIKE` + Python-side fuzzy scoring, `GET /users/{username}/posts`, `POST /posts/{id}/like`). Uvicorn started with `--proxy-headers --forwarded-allow-ips='*'` so external `X-Forwarded-For` headers populate the access-log source-IP field.
- **DB-side preparation:** seed bumped from 1 000 → 10 000 rows from a fixed 50-username pool; `posts_author_idx` added; **no** index on `content` (`/posts/search` is intentionally CPU-bound under concurrency).
- **`scripts/load_runner.py`** (httpx + asyncio, PEP 723 inline-deps): weighted endpoint mix (60/20/15/5), VU ramp, varied `X-Forwarded-For` from a 50-IP pool in TEST-NET-3 (RFC 5737 `203.0.113.X`).
- **OpenSRE host bootstrap:** `opensre_host/user_data.sh.tftpl` extended to install `python3-pip` + `httpx` (system-wide via `pip install --break-system-packages`), then write `/opt/opensre/load_runner.py` via heredoc. The host gets replaced on apply (because of `user_data_replace_on_change = true` already in Plan 2) and re-bootstraps with the new tooling.

**New code/edits:**
- `backend/src/app/main.py` (4 handlers added; CORS `allow_methods` widened to include `POST`).
- `backend/tests/test_posts.py` (TDD pairs for all 4 handlers — 6 new tests).
- `backend/Dockerfile` (Uvicorn flags).
- `scripts/seed_posts.py` (10 k rows + 50-user pool + author index).
- `scripts/load_runner.py` (new).
- `opensre_host/user_data.sh.tftpl` (Python install + load runner heredoc).

**Deploy pattern:** code-first (run pytest), then build/push image, force-roll ECS service, re-seed RDS via SSM port-forward, then `terraform apply` to replace the OpenSRE host. Smoke test runs `aws ssm send-command python3 /opt/opensre/load_runner.py http://<eip>:8080 --duration 60 --max-vus 50` and verifies the SUT log group fills with realistic-looking traffic and CPU climbs ≥ 50 %.

**Telegram dependency:** none directly — Plan 4 doesn't touch the alerting chain. The host replacement in Task 10 re-fires the Plan-2 bootstrap "hello" Telegram message as a side effect.

---

## Plan 5 — FIS chaos + end-to-end 📝

**File:** `docs/superpowers/plans/2026-05-08-fis-chaos.md` (5 tasks)

**Goal:** Two FIS experiment templates that, when started, produce real degradation on the SUT, fire Plan 3's alarms, and trigger Plan 2's `opensre investigate` → built-in Telegram messaging chain — meeting the spec §11 success criterion end-to-end.

**New components:**
- **FIS service role** (trust `fis.amazonaws.com`) with two inline policies:
  - For `aws:ssm:send-command` (used by `cpu-load-burst`): `ssm:SendCommand` on `AWS-RunShellScript` document + EC2 instance ARNs in the account/region (so a host-replace doesn't break the IAM scope), `ssm:ListCommands`/`CancelCommand`/`GetCommandInvocation`, `ec2:DescribeInstances` for tag resolution. Mirrors AWS's managed `AWSFaultInjectionSimulatorEC2Access` policy, scoped down.
  - For `aws:rds:reboot-db-instances`: `rds:RebootDBInstance`, `rds:DescribeDBInstances` on the demo RDS ARN.
- **`aws_fis_experiment_template.cpu_load_burst`** (`aws:ssm:send-command`): targets `aws:ec2:instance` by tag `Role=opensre-agent` (already present on the OpenSRE host from Plan 2); parameters `documentArn=AWS-RunShellScript`, `duration=PT4M`, `documentParameters` JSON-encoded with `commands=["python3 /opt/opensre/load_runner.py http://<eip>:8080 --duration 180 --ramp 30 --max-vus 200 --max-id 10000"]`. Stop condition: none.
- **`aws_fis_experiment_template.rds_reboot`** (`aws:rds:reboot-db-instances`): targets the demo RDS instance by ARN; parameter `forceFailover=false`. Stop condition: none.

**New scripts:**
- `scripts/start_chaos.sh` — wrapper around `aws fis start-experiment` accepting `cpu` or `rds`; resolves the experiment-template ID via `terraform output`; optional `--follow` tails `/aws/ssm/opensre-investigate`.

**Verification (the MVP success criterion, spec §11):**
1. `./scripts/start_chaos.sh cpu` → SSM dispatches `load_runner.py` to the OpenSRE host; SUT log group fills with weighted access-log entries (60/20/15/5 mix) with varied `203.0.113.X` source IPs; alarm `sut-cpu-saturation` transitions OK→ALARM in 60–120 s; Lambda log shows `ssm:SendCommand sent`; SSM log shows OpenSRE stdout; RCA in Telegram within ~3 min, citing **traffic-driven evidence** (path mix, source-IP variety, top endpoints).
2. `./scripts/start_chaos.sh rds` (with light traffic to provoke the connection-pool failure) → alarm `sut-db-connection-errors` transitions in 90–180 s; same chain; RCA references the RDS reboot event.
3. OpenClaw bot in the same group ingests both RCAs.

**Time budget:** alarm-to-Telegram p95 ≈ 3 min (spec §5). Anthropic API latency dominates; Telegram POST adds <1 s.

**Cost:** ~$0.40 per CPU experiment (4 min × $0.10/action-min — FIS bills the action's `duration` parameter, not actual run time); RDS reboot is near-free. A few demo runs/month is well under $1. To reduce, lower `duration` to `PT3M` once the load runner reliably completes inside that window.

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

Each plan must be fully applied + verified before the next one begins, because each Plan N+1 references Plan N's outputs (or installed artefacts, in the case of Plan 5 → Plan 4's `load_runner.py`):

```
Plan 1 apply -> seed RDS (1k) -> deploy UI       (foundation working)
   ↓
Plan 2 apply (host_enabled=false)
populate Secrets Manager (anthropic, telegram_bot_token)
Plan 2 apply (host_enabled=true) -> bootstrap "hello" in Telegram
test_opensre_alert.sh -> RCA in Telegram          (agent layer working)
   ↓
Plan 3 apply (additive)
set-alarm-state -> RCA in Telegram                (alert pipeline working)
   ↓
Plan 4: backend tests -> push image -> roll ECS
       -> SSM port-forward -> re-seed RDS to 10k
       -> terraform apply (replaces OpenSRE host with python3-pip + httpx + load_runner.py)
       -> SSM RunCommand: load_runner.py 60 s burst -> realistic logs in /ecs/...  (load tooling ready)
   ↓
Plan 5 apply (additive; FIS IAM + 2 experiment templates)
start_chaos.sh cpu|rds -> RCA in Telegram        (MVP success criterion ✓)
```

Toggling `var.opensre_host_enabled = false` cleanly tears down Plans 2, 3, and 4's host-side install (the EC2 and the Lambda that depends on it) without touching Plans 1, 3 alarms/SNS, 4's backend/seed/script artefacts, or 5's FIS templates. Re-flipping to `true` re-bootstraps the agent layer (re-installs `load_runner.py` from user_data) and restores the chain.

---

## How to resume after a context reload

1. Read this doc.
2. Read the current plan file (Plan 2, 3, 4, or 5) for task-level detail.
3. Read the spec only if the plan is ambiguous — each plan is self-contained.
4. Run `cd infra && terraform output` and `cd infra && terraform state list` to recover the actual deployed state.
5. Continue from the first unchecked `- [ ]` step in the current plan.

All five plan files are drafted and should not need re-writing unless the spec changes substantively. The 2026-05-09 spec revision (CPU chaos: synthetic stress → load-driven burst) is the most recent substantive change; if the spec is revised again, re-flow the affected plan(s).
