# OpenSRE MVP — Plans 1–4 Overview

**Source spec:** [`2026-05-08-open-sre-mvp-design.md`](../specs/2026-05-08-open-sre-mvp-design.md)
**Date:** 2026-05-08
**Purpose:** Context-management aid. Re-load this doc to recover the full mental model of the four-plan rollout when conversation context is reset.

---

## End-state success criterion (from spec §1, §11)

```
Operator: aws fis start-experiment --experiment-template-id <cpu-stress|rds-reboot>
                                ↓
            within ~3 minutes, useful RCA in #sre-incidents containing:
              • alarm that fired
              • evidence (CW metrics, logs, RDS events)
              • root-cause hypothesis
              • recommended next action
```

---

## Plan status

| # | Plan | File | Status | Verifies |
|---|---|---|---|---|
| 1 | Foundation + SUT + UI | `2026-05-08-foundation-sut-ui.md` | ✅ Done | Posts table renders in browser; backend on `/posts` returns 1k seeded rows |
| 2 | OpenSRE host | `2026-05-08-opensre-host.md` | 📝 To write | Synthetic alert via SSM → real RCA in Slack |
| 3 | Alert pipeline | `2026-05-08-alert-pipeline.md` | 📝 To write | Manually-fired CW alarm → Lambda → SSM → host → RCA in Slack |
| 4 | FIS chaos + e2e | `2026-05-08-fis-chaos.md` | 📝 To write | `start_chaos.sh cpu\|rds` → alarm → RCA in Slack within ~3 min |

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

**Goal:** Stand up the long-lived OpenSRE EC2 that runs `opensre investigate` against synthetic alerts and posts RCAs to Slack. Adds the **agent layer**; nothing yet auto-routes CW alarms here.

**New components:**
- **Secrets Manager shells:** `opensre/anthropic_api_key`, `opensre/slack_bot_token` (created empty by Terraform; values populated manually via `aws secretsmanager put-secret-value`).
- **OpenSRE EC2:** separate `t3.micro` AL2023 in `public_a` subnet. SSM-only access (no inbound SG).
- **IAM (instance role):** `AmazonSSMManagedInstanceCore` + inline read-only AWS for investigation (`ec2:Describe*`, `ecs:Describe*`/`List*`, `rds:DescribeDBInstances`/`DescribeEvents`, `cloudwatch:GetMetricData`/`ListMetrics`, `logs:FilterLogEvents`/`GetLogEvents`, `sts:GetCallerIdentity`) + inline `secretsmanager:GetSecretValue` on the two named secrets only.
- **Bootstrap:** `opensre_host/user_data.sh.tftpl` installs OpenSRE CLI, fetches secrets via instance role, writes `/etc/opensre/.env`, runs `opensre onboard --headless`, runs `opensre integrations verify` as smoke test. Logs to `/var/log/opensre-bootstrap/`.
- **SSM log group:** `/aws/ssm/opensre-investigate` (7-day retention) — receives stdout/stderr from every `opensre investigate` invocation.
- **Helper script:** `scripts/test_opensre_alert.sh` — sends synthetic alert via SSM RunCommand, polls for completion, reports status.

**New variables/outputs:**
- `var.opensre_slack_channel` (default `#sre-incidents`), `var.opensre_host_enabled` (toggle for two-phase apply).
- Outputs: `anthropic_secret_id`, `slack_secret_id`, `opensre_host_instance_id`, `opensre_ssm_log_group`.

**Deploy pattern:** two-phase apply (`opensre_host_enabled = false` → populate secrets → `opensre_host_enabled = true`). Mirrors Plan 1's `sut_desired_count` toggle.

**Verification:**
1. SSM-managed-status check: `aws ssm describe-instance-information --filters "Key=InstanceIds,Values=<id>"` shows the host as Online.
2. `opensre integrations verify` via SSM RunCommand exits 0; output shows AWS, Anthropic, Slack all green.
3. `./scripts/test_opensre_alert.sh` sends a synthetic CPU-saturation alert; status reaches `Success`; an RCA appears in `#sre-incidents`.

**Doc verification gate:** Before Tasks 4 (user_data) and 7 (integrations verify), confirm OpenSRE CLI install URL + onboarding flags at https://www.opensre.com/docs.

---

## Plan 3 — Alert pipeline 📝

**Target file:** `docs/superpowers/plans/2026-05-08-alert-pipeline.md` (planned ~7 tasks)

**Goal:** Wire CloudWatch alarms → SNS → Lambda → `ssm:SendCommand` to the Plan-2 host. After this plan, manually setting an alarm to ALARM produces a real RCA without any FIS involvement.

**New components:**
- **SNS topic:** `opensre-alarms`. Lambda is the only subscription.
- **Lambda `ingest_alarm`** (Python 3.12, 256 MB, 30 s timeout, zip package with vendored boto3): parses SNS payload → builds normalised alert JSON (per spec §5.3) → base64-encodes → calls `ssm:SendCommand` against the OpenSRE host with `CloudWatchOutputConfig` enabled (`/aws/ssm/opensre-investigate`).
- **Lambda execution role:** Basic Lambda execution + `ssm:SendCommand` scoped to the OpenSRE host instance ARN + `AWS-RunShellScript` document ARN.
- **Lambda log group:** `/aws/lambda/ingest_alarm` (7-day retention).
- **CloudWatch Logs metric filter `sut-db-connection-errors`** on `/ecs/opensre-demo-sut`: pattern `?"could not connect to server" ?"connection timeout" ?"OperationalError"`. Emits `OpenSRE/SUT/DBConnectionErrors`.
- **CloudWatch Alarm `sut-cpu-saturation`:** `AWS/ECS CPUUtilization` (service-level) ≥ 80%, 1 datapoint / 1 min, dimensions `ClusterName=opensre-demo`, `ServiceName=opensre-demo-sut`. Action → SNS topic.
- **CloudWatch Alarm `sut-db-connection-errors`:** `OpenSRE/SUT/DBConnectionErrors` ≥ 1 over 1 min. Action → SNS topic.

**New code:**
- `lambda/ingest_alarm/handler.py` (SNS event → normalize → SSM SendCommand)
- `lambda/ingest_alarm/requirements.txt`
- `lambda/ingest_alarm/tests/test_handler.py` (unit tests with moto-style stubs)

**Deploy pattern:** single `terraform apply`. Lambda zip built locally and uploaded.

**Verification:**
1. Lambda unit tests pass (handler correctness without AWS).
2. `aws cloudwatch set-alarm-state --alarm-name sut-cpu-saturation --state-value ALARM --state-reason "manual test"` triggers the SNS message.
3. Lambda log group shows the invocation; SSM command-id is logged.
4. `/aws/ssm/opensre-investigate` shows OpenSRE's stdout for the synthetic alert.
5. RCA appears in `#sre-incidents`.

**Repeat** for the DB-connection-errors alarm.

---

## Plan 4 — FIS chaos + end-to-end 📝

**Target file:** `docs/superpowers/plans/2026-05-08-fis-chaos.md` (planned ~5 tasks)

**Goal:** Two FIS experiment templates that, when started, produce real degradation on the SUT, fire the alarms from Plan 3, and produce real RCAs from Plan 2 — meeting the spec §11 success criterion end-to-end.

**New components:**
- **FIS IAM role** (trust `fis.amazonaws.com`):
  - For `aws:ecs:task-cpu-stress`: `ecs:DescribeTasks`/`ListTasks`/`DescribeContainerInstances`, `ec2:DescribeInstances`, `ssm:SendCommand` on `AWSFIS-Run-CPU-Stress` doc + the SUT container instance, `ssm:ListCommands`, `ssm:CancelCommand`.
  - For `aws:rds:reboot-db-instances`: `rds:RebootDBInstance`, `rds:DescribeDBInstances`.
- **FIS experiment template `cpu-stress-ecs`** (`aws:ecs:task-cpu-stress`): tag-targeted to the SUT (`Project=opensre-demo`); stop conditions: any.
- **FIS experiment template `rds-reboot`** (`aws:rds:reboot-db-instances`): targets the demo RDS instance.

**New code:**
- `chaos/cpu-stress.json` (FIS template body)
- `chaos/rds-reboot.json` (FIS template body)

**New scripts:**
- `scripts/start_chaos.sh` — wrapper around `aws fis start-experiment` with selector (`cpu` | `rds`) and tail-follow on `/aws/ssm/opensre-investigate`.

**Verification (end-to-end demo per spec §11):**
1. `./scripts/start_chaos.sh cpu` → within ~3 min, RCA in `#sre-incidents` referencing CPU saturation on `opensre-demo-sut`.
2. `./scripts/start_chaos.sh rds` → within ~3 min, RCA referencing the RDS reboot event (via `rds:DescribeEvents`).
3. CloudWatch Logs Insights query against `/aws/ssm/opensre-investigate` shows the full agent reasoning trace for both runs.

**Time budget:** alarm-to-Slack p95 ≈ 3 min (spec §5). Anthropic API latency dominates.

---

## Cross-plan invariants

These hold across all four plans and the design enforces them:

- **No production credentials in repo.** AWS profiles + Secrets Manager only. `terraform.tfvars` is gitignored.
- **AWS Free Tier compliance** (best-effort, see spec §10). Two t3.micros at 100% uptime ≈ 1 460 h/mo > 750 h free quota; operator tears down between demos or accepts ~$8/mo overage.
- **No DLQ, no dedup, no retry infrastructure** — silent drops on persistent failure are acceptable; debug via CloudWatch Logs.
- **No DynamoDB.** OpenSRE owns its own investigation state on the EC2 host.
- **Slack message + SSM CW Logs stream are the durable artefacts.**
- **Single account, single region** (default `us-east-1`).

---

## How to resume after a context reload

1. Read this doc.
2. Read the current plan file (Plan 2 / 3 / 4) for task-level detail.
3. Read the spec only if the plan is ambiguous — the plan should be self-contained.
4. Run `cd infra && terraform output` and `cd infra && terraform state list` to recover the actual deployed state.
5. Continue from the first unchecked `- [ ]` step in the current plan.

If a plan file does not yet exist, ask Claude to write it — point at this overview + the spec section(s) referenced under that plan above.
