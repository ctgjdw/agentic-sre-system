# OpenSRE MVP — Design

**Status:** Approved 2026-05-08
**Source:** Brainstorming session, 2026-05-08
**Stack:** AWS Free Tier · ECS-on-EC2 · RDS PostgreSQL · CloudWatch · AWS FIS · OpenSRE (local-CLI on EC2) · Anthropic Claude · Next.js + shadcn/ui

---

## 1. Goal

Build the smallest end-to-end demo that proves this loop, on AWS Free Tier:

> FIS chaos event → CloudWatch alarm → SNS → Lambda shim → SSM RunCommand on OpenSRE EC2 → `opensre investigate` → RCA posted to Slack via OpenSRE's bot

This is a **simplified first-cut demo** that takes an alert from AWS, sends it to OpenSRE for diagnosis, and outputs the RCA to Slack for human follow-up. It supersedes the prior `sre-agents/` design (custom 7-agent orchestrator on Fargate + OpenSearch), which was deemed too costly in time and effort for current needs.

### Principles (from `CLAUDE.md`)

- MVP-first. Smallest end-to-end slice.
- AWS Free Tier where it fits.
- No production credentials in the repo. AWS Secrets Manager + IAM only.
- Always refer to current online documentation before action.

### Success criterion

End-to-end demo: operator runs `aws fis start-experiment` for either of the two templates → within ~3 minutes a useful RCA appears in `#sre-incidents` → the audience can read OpenSRE's reasoning, supporting evidence, and recommended next action.

---

## 2. Locked decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Scope | Replacement first-cut MVP. No human-approval buttons, no automated remediation, no custom multi-agent code. |
| 2 | Agent layer | OpenSRE local-CLI binary, running long-lived on a free-tier EC2 host |
| 3 | Alert ingestion bridge | CloudWatch alarm → SNS → Lambda → `ssm:SendCommand` (with `CloudWatchOutputConfig` enabled) → `opensre investigate -i alert.json` on EC2 |
| 4 | LLM provider | Anthropic API, default model `claude-sonnet-4-6` (OpenSRE default) |
| 5 | Output channel | OpenSRE's built-in Slack bot (informational RCA only, no interactive components) |
| 6 | Chaos surface | Two FIS experiments: `aws:ecs:task-cpu-stress` (compute) and `aws:rds:reboot-db-instances` (data) |
| 7 | SUT app | Single FastAPI service on ECS-on-EC2, backed by RDS PostgreSQL `db.t3.micro`. JSON API only — `GET /health`, `GET /posts` |
| 8 | UI app | Separate Next.js (App Router, `output: 'export'`) + Tailwind v4 + shadcn/ui, static-exported to S3 website-hosting bucket |
| 9 | Workload | None automated. Manual browser refreshes generate traffic. |
| 10 | Alarms | (a) `sut-cpu-saturation` on `AWS/ECS CPUUtilization ≥ 80%` (service-level, percent); (b) `sut-db-connection-errors` on a custom metric from a CloudWatch Logs metric filter |
| 11 | Persistence | OpenSRE owns its own investigation state on the EC2 host. No DynamoDB on our side. |

---

## 3. System architecture

```
                          ┌──────────────────────────────────┐
                          │          AWS account             │
                          │                                  │
   ┌─────────────┐        │   ┌────────────────────────┐    │
   │  FIS        │        │   │  SUT (chaos target)    │    │
   │ Experiment  │────────┼──▶│  ┌─────────────────┐   │    │
   │  templates  │        │   │  │ ECS service     │   │    │
   │  (CPU/RDS)  │        │   │  │ on EC2 capacity │   │    │
   └─────────────┘        │   │  │ (1 t3.micro)    │   │    │
                          │   │  │ FastAPI         │   │    │
                          │   │  └────┬────────────┘   │    │
                          │   │       │                │    │
                          │   │       ▼                │    │
                          │   │  ┌─────────────────┐   │    │
                          │   │  │ RDS PostgreSQL  │   │    │
                          │   │  │ db.t3.micro     │   │    │
                          │   │  │ posts (1k rows) │   │    │
                          │   │  └─────────────────┘   │    │
                          │   └──────┬─────────────────┘    │
                          │          │ metrics + logs       │
                          │          ▼                      │
                          │   ┌──────────────┐              │
                          │   │ CloudWatch   │              │
                          │   │  • log group │              │
                          │   │    /ecs/...  │              │
                          │   │  • metric    │              │
                          │   │    filter    │              │
                          │   │  • Alarms ×2 │              │
                          │   └──────┬───────┘              │
                          │          │ ALARM                │
                          │          ▼                      │
                          │   ┌──────────────┐              │
                          │   │ SNS topic    │              │
                          │   │ opensre-     │              │
                          │   │ alarms       │              │
                          │   └──────┬───────┘              │
                          │          │                      │
                          │          ▼                      │
                          │   ┌──────────────────┐          │
                          │   │ Lambda shim      │          │
                          │   │ ingest_alarm     │          │
                          │   │ (Python, 256 MB) │          │
                          │   └──────┬───────────┘          │
                          │          │ ssm:SendCommand      │
                          │          │ + CloudWatchOutput   │
                          │          ▼                      │
                          │   ┌────────────────────────┐    │
                          │   │  OpenSRE host          │    │
                          │   │  EC2 t3.micro          │    │
                          │   │  • opensre CLI         │    │
                          │   │  • SSM agent           │    │
                          │   │  • configured for:     │    │
                          │   │    AWS, RDS, CW, Slack │────┼──▶ ┌─────────────────┐
                          │   │  • LLM_PROVIDER=       │    │    │ Anthropic API   │
                          │   │    anthropic           │    │    │ (claude-sonnet) │
                          │   └──────┬─────────────────┘    │    └─────────────────┘
                          │          │ stdout+stderr        │
                          │          ▼                      │
                          │   ┌──────────────────┐          │
                          │   │ CloudWatch Logs  │          │
                          │   │ /aws/ssm/        │          │
                          │   │ opensre-         │          │
                          │   │ investigate      │          │
                          │   └──────────────────┘          │
                          └──────────────────────────────────┘

   ┌─────────────┐
   │ Browser     │   GET /  →  S3 website (UI)
   │ (operator   │   fetch /posts → SUT EC2 EIP:8080 (CORS)
   │  & demo     │
   │  audience)  │
   └─────────────┘                            OpenSRE bot ─────▶ Slack #sre-incidents
                                              (posts directly
                                               from EC2)
```

### Single-region, single-account assumption

Everything provisioned in one AWS account, one region (deployer's choice; default `us-east-1`). Free-tier eligibility resets after 12 months for first-time accounts.

---

## 4. Components

### Compute & data

| Component | Shape | Free-tier note |
|---|---|---|
| **SUT app** | FastAPI, ~80 LOC. Endpoints: `GET /health` (no DB, returns 200), `GET /posts?limit=50` (SELECT from RDS, returns JSON). CORS enabled for the S3 website origin only. | — |
| **SUT runtime** | ECS service `opensre-demo-sut`, 1 task, EC2 capacity provider with 1× `t3.micro` Amazon Linux 2023 ECS-optimised. Bridge networking, container port 8080 → host 8080. Elastic IP attached to the host so the UI's baked-in API URL is stable. | EC2: 750 free hours / 12 mo (shared with the OpenSRE host — see note in §10). |
| **Data tier** | RDS PostgreSQL `db.t3.micro`, 20 GB gp3, single-AZ, publicly inaccessible (private subnet, SG allows 5432 from SUT host SG only). One table `posts`. | RDS: 750 free hours + 20 GB / 12 mo. |
| **OpenSRE host** | Separate t3.micro (Amazon Linux 2023). User-data installs `opensre` (curl install), pulls Anthropic key + Slack bot token from Secrets Manager, writes `/etc/opensre/.env`, runs `opensre onboard` headlessly via env vars, runs `opensre integrations verify` as a smoke test. | EC2: counts toward the same 750-hour pool. Two t3.micros at 100% uptime ≈ 1 460 hours/mo, exceeds 750. Operator tears down between demos, or accepts a few cents/month past the cap. |
| **UI app** | Next.js (App Router) static export, served from `s3://opensre-demo-ui/` with website hosting enabled. shadcn/ui Table + Refresh button + Skeleton loader. Single page. | S3: 5 GB free / 12 mo; bandwidth modest for demos. |

### DB schema

```sql
CREATE TABLE posts (
  id           SERIAL PRIMARY KEY,
  author       TEXT NOT NULL,
  content      TEXT NOT NULL,
  likes        INT  NOT NULL DEFAULT 0,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX posts_created_at_idx ON posts (created_at DESC);
```

Seeded via `scripts/seed_posts.py` (Python `faker` library) with 1 000 fake rows: `faker.user_name()`, `faker.text(max_nb_chars=200)`, random likes 0–500, random `created_at` over the last 30 days. Idempotent guard: `count(*)` check before inserting.

### Glue & control plane

| Component | Purpose |
|---|---|
| **CloudWatch Log group `/ecs/opensre-demo-sut`** | App logs via the `awslogs` ECS log driver. 7-day retention. |
| **CloudWatch Logs Metric Filter `sut-db-connection-errors`** | Pattern: `?"could not connect to server" ?"connection timeout" ?"OperationalError"`. Emits custom metric `OpenSRE/SUT/DBConnectionErrors`. |
| **CloudWatch Alarm 1 `sut-cpu-saturation`** | Metric: `AWS/ECS CPUUtilization` (service-level, percent — emitted by default with no Container Insights needed) ≥ 80%, 1 datapoint / 1 min. Dimensions: `ClusterName=opensre-demo`, `ServiceName=opensre-demo-sut`. Action → SNS topic. |
| **CloudWatch Alarm 2 `sut-db-connection-errors`** | Metric: `OpenSRE/SUT/DBConnectionErrors ≥ 1` over 1 min. Action → SNS topic. |
| **SNS topic `opensre-alarms`** | Subscriptions: the Lambda shim. |
| **Lambda `ingest_alarm`** | Python 3.12, 256 MB, timeout 30 s. Receives SNS event, normalises into the alert payload below, calls `ssm:SendCommand` against the OpenSRE host with `CloudWatchOutputConfig` enabled. |
| **CloudWatch Log group `/aws/ssm/opensre-investigate`** | SSM-streamed stdout/stderr per invocation. 7-day retention. |
| **CloudWatch Log group `/aws/lambda/ingest_alarm`** | Lambda execution traces. 7-day retention. |
| **Secrets Manager** | Two secrets: `opensre/anthropic_api_key`, `opensre/slack_bot_token`. Read by the OpenSRE host on boot only. |
| **FIS experiment templates** | Two: `cpu-stress-ecs` (`aws:ecs:task-cpu-stress`), `rds-reboot` (`aws:rds:reboot-db-instances`). Stop conditions: any. Tag-targeted to the SUT (`Project=opensre-demo`). |

### IAM (least privilege)

- **OpenSRE host instance role:**
  - `AmazonSSMManagedInstanceCore` (managed) — for SSM RunCommand
  - Inline policy: read-only AWS access per OpenSRE's documented requirement — `ec2:Describe*`, `ecs:Describe*`, `ecs:List*`, `rds:DescribeDBInstances`, `rds:DescribeEvents`, `cloudwatch:GetMetricData`, `cloudwatch:ListMetrics`, `logs:FilterLogEvents`, `logs:GetLogEvents`, `sts:GetCallerIdentity`
  - Inline policy: `secretsmanager:GetSecretValue` on the two named secrets only
- **SUT EC2 instance role:**
  - ECS-optimised AMI default policies (`AmazonEC2ContainerServiceforEC2Role`)
  - `logs:CreateLogStream`, `logs:PutLogEvents` for the SUT log group
- **Lambda execution role:**
  - Basic Lambda execution (CloudWatch Logs)
  - `ssm:SendCommand` scoped to the OpenSRE host's instance ARN
  - `ssm:SendCommand` scoped to `arn:aws:ssm:<region>::document/AWS-RunShellScript`
- **FIS role:**
  - For `aws:ecs:task-cpu-stress` (which AWS FIS implements by invoking SSM RunCommand against the ECS task's container instance with the `AWSFIS-Run-CPU-Stress` document): `ecs:DescribeTasks`, `ecs:ListTasks`, `ecs:DescribeContainerInstances`, `ec2:DescribeInstances`, `ssm:SendCommand` on document `AWSFIS-Run-CPU-Stress` and on the SUT container instance, `ssm:ListCommands`, `ssm:CancelCommand`
  - For `aws:rds:reboot-db-instances`: `rds:RebootDBInstance`, `rds:DescribeDBInstances`
  - Trust policy: `fis.amazonaws.com`. Plan resolves the exact permissions list by referencing AWS's published FIS-action permission tables at implementation time.

### Network

- One VPC, two subnets (one public for EC2s, one private for RDS) across two AZs (RDS prefers two AZs for the subnet group even in single-AZ mode).
- IGW for the public subnet. No NAT Gateway (saves $35/mo and explicitly out of scope; OpenSRE host reaches AWS APIs over the public internet via the IGW; outbound HTTPS only).
- Security groups:
  - **SUT host SG:** inbound 8080 from a configurable CIDR (default: deployer's home IP); outbound all
  - **OpenSRE host SG:** outbound all; no inbound (managed via SSM)
  - **RDS SG:** inbound 5432 from SUT host SG only

### What we explicitly *don't* deploy

- No DynamoDB / no Slack callback Lambda (no buttons → no callbacks → no state on our side).
- No S3 runbook bucket (no runbooks in this MVP — RCA only).
- No DLQ on SNS or Lambda (acceptable risk for first-cut).
- No NAT Gateway / VPC endpoints.
- No ALB in front of the SUT or UI (HTTP, public IP, S3 website URL).
- No CloudFront / TLS / DNS.

---

## 5. Data flow & lifecycle

### One-time bootstrap

```
1. terraform/cdk apply → provisions VPC, RDS, ECS cluster, EC2s, SNS, Lambda, FIS templates,
                         CloudWatch alarms + log group + metric filter, SSM IAM, secrets shells
2. Populate Secrets Manager: anthropic_api_key, slack_bot_token  (one-time, manual)
3. Wait for OpenSRE host user-data to finish:
     installs opensre → fetches secrets → opensre onboard --headless
                     → opensre integrations verify  (smoke test passes)
4. python scripts/seed_posts.py  (against RDS endpoint, inserts 1 000 fake rows; idempotent)
5. cd ui && NEXT_PUBLIC_API_URL=http://<eip>:8080 npm run build
   aws s3 sync out/ s3://opensre-demo-ui/
6. Open the S3 website URL → table renders → demo is ready
```

### Per-incident flow

```
t=0       Operator runs:  aws fis start-experiment --experiment-template-id <cpu-stress-or-rds-reboot>

t≈0..30s  FIS effect ramps (CPU stress on the task | RDS reboot in progress)
          ↓
          ECS metrics / SUT app logs reflect degradation
          ↓
t≈60..90s CloudWatch alarm transitions OK → ALARM
          • CPU scenario: Alarm 1 (sut-cpu-saturation)
          • RDS scenario: Alarm 2 (sut-db-connection-errors)
          ↓
          Alarm action publishes to SNS topic opensre-alarms
          ↓
t≈90s     Lambda ingest_alarm fires (SNS event source)

           Lambda steps (≤10 s wall):
             a. Parse SNS payload → CloudWatch alarm message envelope
             b. Build alert payload (see §5.3); generate a unique invocation_id (uuid4)
             c. Encode payload as base64 (avoids shell-escaping pitfalls):
                  payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
                  alert_path  = f'/tmp/alert-{invocation_id}.json'
             d. ssm.send_command(
                  InstanceIds=[OPENSRE_HOST_ID],
                  DocumentName='AWS-RunShellScript',
                  Parameters={'commands': [
                    f"echo '{payload_b64}' | base64 -d > {alert_path}",
                    f"/usr/local/bin/opensre investigate -i {alert_path}",
                  ]},
                  CloudWatchOutputConfig={
                    'CloudWatchLogGroupName': '/aws/ssm/opensre-investigate',
                    'CloudWatchOutputEnabled': True,
                  },
                  TimeoutSeconds=600,
                  Comment=f'opensre-{alarm_name}-{invocation_id}',
                )
             e. Return {commandId, alarmName, invocationId} (Lambda exits; investigation continues async)

t≈90..210s  opensre investigate runs on the EC2 host
            • reads /tmp/alert-*.json
            • queries AWS via its IAM role (cloudwatch:GetMetricData, ecs:Describe*,
                                            rds:DescribeEvents, logs:FilterLogEvents)
            • calls Anthropic API (claude-sonnet-4-6) for the reasoning loop
            • iterates until confidence threshold or step cap
            • posts RCA to Slack via its configured bot

t≈210s    Slack message lands in #sre-incidents
          stdout/stderr for the entire run is in CloudWatch Logs
          /aws/ssm/opensre-investigate/<commandId>/.../stdout
```

Total p95 budget: alarm-to-Slack ≈ 3 minutes. The Anthropic call inside the agent loop is the dominant variable; multi-step investigations may push p95 closer to 4 minutes.

### Alert payload shape (Lambda → opensre)

```json
{
  "source": "aws-cloudwatch",
  "alert_name": "sut-cpu-saturation",
  "state": "ALARM",
  "state_change_time": "2026-05-08T12:34:56Z",
  "region": "us-east-1",
  "resource": {
    "type": "ecs-service",
    "cluster": "opensre-demo",
    "service": "opensre-demo-sut",
    "task_definition": "opensre-demo-sut:7"
  },
  "metric": {
    "namespace": "AWS/ECS",
    "name": "CPUUtilization",
    "threshold": 80,
    "value_at_breach": 99.4,
    "period_seconds": 60
  },
  "raw_sns_message": { "...full SNS body, unmodified..." }
}
```

For the RDS-reboot alarm, `resource.type` is `rds-instance` with `instance_identifier`, and `metric.namespace` is `OpenSRE/SUT` (the custom metric from the log filter). `raw_sns_message` is preserved unmodified so OpenSRE has the source-of-truth if it wants to dig.

### State

- **No DynamoDB.** OpenSRE owns its own investigation state on the EC2 host (in its working dir). Each invocation is independent.
- **No deduplication on our side.** If the same alarm fires twice, we run the agent twice. CloudWatch alarms have natural debouncing via evaluation periods.
- **Slack message is the durable artifact.** Plus the SSM CloudWatch Logs stream for raw stdout/stderr.

---

## 6. Failure modes

### Principle

Every failure surfaces in CloudWatch Logs. The operator's debug path is: "Slack didn't show an RCA → check Lambda log group → check SSM log group → SSH to OpenSRE host". For a first-cut demo we accept that some failures result in silent drops; we don't build retry/DLQ infrastructure to handle them.

### Taxonomy

| Failure | Where it shows | Mitigation |
|---|---|---|
| Lambda parse error (malformed SNS payload) | Lambda log group, exception stack trace | None for first-cut. SNS retries 3× by default; if all 3 fail, message is dropped. |
| `ssm:SendCommand` rejected (host offline / IAM denied / wrong instance ID) | Lambda log group, `botocore.exceptions.ClientError` | Lambda exits non-zero. SNS will retry per delivery policy. Pre-verify the instance ID at deploy time. |
| OpenSRE host SSM agent disconnected | `SendCommand` returns success; the command never runs | Manual operator inspection. Healthcheck deferred (§8). |
| `opensre investigate` exits non-zero (config missing, integration not connected, LLM key invalid) | `/aws/ssm/opensre-investigate` stderr stream | Operator inspects the stream; no auto-retry. |
| Anthropic API rate-limit / 5xx | OpenSRE handles internally (its own retry loop) | Trust OpenSRE; degraded RCA in Slack notes the failure. |
| Slack post fails (bot not in channel / token expired) | SSM stderr captures OpenSRE's error; the RCA itself is also visible in the SSM stdout stream from the same invocation. | Operator fixes integration and reruns. No auto-repost. |
| RDS unreachable from OpenSRE during RDS-reboot scenario | Expected — the failure being investigated. OpenSRE uses `DescribeEvents` (control-plane), not a DB connection. | None needed. |
| OpenSRE EC2 itself dies | Nothing reaches Slack until it's back. | Out of scope. The OpenSRE host is intentionally separate from the SUT so chaos targeting the SUT doesn't take it down. |

### Hard-coded soft timeout

`SendCommand` is called with `TimeoutSeconds=600`. If `opensre investigate` hasn't returned in 10 minutes, SSM kills it. Bounds the worst case; prevents a runaway agent loop from holding the EC2.

### Observability

Two log groups, both 7-day retention:

- `/aws/lambda/ingest_alarm` — Lambda execution traces
- `/aws/ssm/opensre-investigate` — one stream per `opensre investigate` invocation, `stdout` + `stderr` separately

Both searchable via CloudWatch Logs Insights. No custom metrics, no dashboards in v1.

---

## 7. Out of scope / explicit YAGNI

| Item | Why deferred |
|---|---|
| Slack approval/decision buttons | OpenSRE bot doesn't expose them; first-cut is informational RCA only. |
| DynamoDB incident store | OpenSRE owns investigation state; no parallel record needed. |
| DLQ for SNS / Lambda | First-cut accepts silent drops on persistent failure. Debug via CloudWatch Logs. |
| Idempotency / dedup on alarms | Acceptable to investigate the same alarm twice. |
| Reviewer / second-opinion model | OpenSRE is the agent layer; no second-guessing. |
| Custom CloudWatch dashboard | Use Logs Insights ad-hoc. |
| Multi-account / multi-region | Single account, single region. |
| Authn/authz on the UI | Public S3 website, public IP backend, SG locks down to operator's IP. |
| ALB / TLS / DNS | HTTP-only on `<eip>:8080` and the S3 website URL. |
| OpenSRE host failover / HA | Single t3.micro; if it dies during a demo, that's a known risk. |
| Workload generator | Manual UI refreshes are the load. |
| Cost-tracking / budget alarms | Operator tears down between demos. |
| Self-hosting OpenSRE on LangGraph / Railway | Local CLI on EC2 is the chosen runtime. |
| Multiple FIS scenarios beyond the locked two | CPU stress + RDS reboot only. |
| Combined-chaos scenarios (CPU and RDS at the same time) | Validate single-vector first. |
| Formal test infrastructure (unit, fixture replay, regression) | Not in scope. The two FIS scenarios are the validation. |
| Metrics on the agent system itself (T2R / T2D / accuracy) | Documented as goals only in the prior design; not implemented here. |
| OpenSRE host healthcheck / SSM-status alarm | Defer; manual debug for demo cadence. |

---

## 8. Open items for the implementation plan

These choices affect *how* we build, not *what* we build, so they belong in the plan:

- **IaC tool:** Terraform vs. AWS CDK (Python) vs. SAM. Lean Terraform for AWS-Free-Tier comprehension; CDK acceptable if Python-everywhere is preferred.
- **Lambda packaging:** zip with vendored boto3 pin, or container image. Likely zip — function is tiny.
- **Concrete alarm thresholds:** CPU `≥ 80%`, 1 datapoint of 1 min is the starting point; tune during the first dry-run.
- **OpenSRE Slack channel name + bot scopes:** locked at plan time when the Slack workspace is configured.
- **SUT EC2 AMI:** Amazon Linux 2023 ECS-optimised. Plan pins the exact AMI ID per region (use SSM Parameter Store alias `/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id`).
- **DB password handling:** Secrets Manager + RDS-managed-secret rotation, or static for demo. Probably static for first-cut, rotated by hand.
- **Region default:** `us-east-1` unless the operator specifies otherwise; FIS, ECS, RDS, free tier all consistent there.
- **Slack workspace + channel:** must exist before bootstrap; bot token captured into Secrets Manager.

---

## 9. Repo layout (target)

```
open-sre-agents/
├── CLAUDE.md
├── README.md                     # demo-runbook for the human operator
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-08-open-sre-mvp-design.md   ← this doc
├── infra/                        # IaC (tool TBD — see §8)
│   ├── network.tf|.py             # VPC, subnets, IGW, EIPs, security groups
│   ├── sut.tf|.py                 # ECS cluster + service + EC2 capacity provider
│   ├── rds.tf|.py                 # db.t3.micro + parameter group
│   ├── opensre_host.tf|.py        # OpenSRE EC2 + IAM + SSM-managed-instance role
│   ├── alarms.tf|.py              # log group, metric filter, 2 alarms, SNS topic
│   ├── lambda.tf|.py              # ingest_alarm function + role
│   ├── fis.tf|.py                 # 2 experiment templates + role
│   └── secrets.tf|.py             # Secrets Manager shells (values populated manually)
├── backend/
│   ├── pyproject.toml
│   ├── src/app/
│   │   ├── main.py               # FastAPI: GET /health, GET /posts
│   │   ├── db.py                 # asyncpg pool
│   │   └── settings.py           # env-driven config
│   ├── Dockerfile
│   └── tests/                    # smoke tests only
├── ui/
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── next.config.ts            # output: 'export'
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx              # PostsTable + Refresh
│   │   └── globals.css
│   ├── components/
│   │   ├── posts-table.tsx
│   │   └── ui/                   # shadcn/ui-generated
│   └── lib/api.ts
├── lambda/
│   └── ingest_alarm/
│       ├── handler.py            # SNS event → SSM SendCommand
│       └── requirements.txt
├── opensre_host/
│   ├── user_data.sh              # bootstrap: install opensre, fetch secrets, onboard
│   └── opensre_env.template      # /etc/opensre/.env template
├── scripts/
│   ├── seed_posts.py             # 1 000 fake rows via faker
│   ├── deploy_ui.sh              # next build + s3 sync
│   └── start_chaos.sh            # aws fis start-experiment wrapper
└── chaos/
    ├── cpu-stress.json           # FIS template body
    └── rds-reboot.json           # FIS template body
```

---

## 10. Free-tier cost notes

Within first 12 months for a new AWS account:

| Service | Free-tier quota | This MVP's usage |
|---|---|---|
| EC2 t3.micro | 750 hours/mo | 2 instances × 24×30 h = 1 440 hours/mo if always-on. Tear down between demos, or accept ~$8/mo overage. |
| RDS db.t3.micro | 750 hours/mo + 20 GB | 1 instance, 20 GB. Within quota if torn down or kept under 750 h. |
| Lambda | 1M req/mo + 400 k GB-s | < 100 req/mo expected. Free. |
| SNS | 1M publishes/mo | < 100 publishes/mo. Free. |
| CloudWatch | 5 GB logs ingest, 10 metrics, 10 alarms | Within quota for demo cadence. |
| SSM | Free for managed instances | — |
| Secrets Manager | Not free — $0.40/secret/mo | ~$0.80/mo for two secrets. Acceptable. |
| S3 | 5 GB storage, 20 k GET | UI bundle is < 5 MB. Free. |
| FIS | Pay per action-minute (~$0.10) | < $1/mo at demo cadence. |
| Elastic IP | Free while attached to a running instance | — |

**Realistic monthly cost while idle (demo torn down):** $0.80 (Secrets Manager) + EIP charge if detached. **While running for a demo:** dollars-not-tens-of-dollars per day.

---

## 11. Success criterion (re-stated)

End-to-end demo:

1. Audience opens the S3 website URL → sees the post table populating.
2. Operator runs `aws fis start-experiment --experiment-template-id <cpu-stress|rds-reboot>`.
3. Within ~3 minutes, a useful RCA appears in `#sre-incidents` containing:
   - The alarm that fired
   - Evidence OpenSRE gathered (CloudWatch metrics, logs, RDS events)
   - A hypothesis for root cause
   - A recommended next action
4. CloudWatch Logs Insights shows the full agent stdout for post-mortem inspection.

---

*End of design.*
