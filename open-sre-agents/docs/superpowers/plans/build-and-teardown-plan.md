# OpenSRE MVP — Build & Teardown Runbook

**Goal:** Stand up (and later tear down) the full Plan-1-through-Plan-5 OpenSRE MVP in **any** AWS account / region from a clean checkout, with every operator-specific value parameterised through a single `infra/terraform.tfvars` file.

**End state:** `./scripts/start_chaos.sh cpu` (or `rds`) produces an RCA in the operator's Telegram group within ~3 minutes; `terraform destroy` returns the account to its pre-demo state with no orphaned resources.

**Source plans:** [`2026-05-08-mvp-plans-overview.md`](2026-05-08-mvp-plans-overview.md) and the five referenced plan files. This runbook is a flattened, account-agnostic view of those plans — read this to operate the demo, read the source plans to understand *why* each component exists.

---

## Quick start

Two wrapper scripts ship in `scripts/`. Both run cleanly on macOS, Linux, and Windows Git Bash (no GNU-only flags, no `uuidgen` dependency, port-readiness checked via Python so `/dev/tcp` quirks are avoided).

```bash
# First-time build (interactive — prompts for Anthropic key + Telegram bot token):
./scripts/build.sh

# One-shot teardown (interactive confirmation; --yes to skip):
./scripts/teardown.sh

# Tear down AND wipe local terraform state + tfvars (e.g. before changing accounts):
./scripts/teardown.sh --yes --clean-local
```

`build.sh` orchestrates Phases B–F below: cold apply → image push → seed → secret prompts → hot apply → UI deploy. It is idempotent — re-running after a partial failure skips completed steps. `teardown.sh` stops in-flight FIS experiments first, then runs `terraform destroy`, then verifies cleanup by listing remaining tagged resources.

Read the rest of this document when you need to:
- Understand exactly what each phase does (e.g. for a code review)
- Recover from a failure mode the script doesn't auto-handle
- Adapt the demo to a new account, region, or operator (see [Portability checklist](#portability-checklist))

The phases below are also the manual fallback if the scripts are unavailable.

---

## Table of contents

1. [Reference: per-environment values](#reference-per-environment-values)
2. [Prerequisites](#prerequisites)
3. [Phase A — Configure for this environment](#phase-a--configure-for-this-environment)
4. [Phase B — Bootstrap apply (cold infra)](#phase-b--bootstrap-apply-cold-infra)
5. [Phase C — Backend image & seed data](#phase-c--backend-image--seed-data)
6. [Phase D — Populate Secrets Manager](#phase-d--populate-secrets-manager)
7. [Phase E — Hot apply (SUT task + OpenSRE host)](#phase-e--hot-apply-sut-task--opensre-host)
8. [Phase F — Deploy UI](#phase-f--deploy-ui)
9. [Phase G — Verification gates](#phase-g--verification-gates)
10. [Teardown](#teardown)
11. [Portability checklist](#portability-checklist)
12. [Failure modes & recovery](#failure-modes--recovery)
13. [Time & cost budget](#time--cost-budget)

---

## Reference: per-environment values

Every value in this table changes between AWS accounts/operators. Everything else (resource names, CIDRs, IAM roles) is derived from `${var.project}` and stays fixed.

| Variable | Where set | Type | Example | Why it must be per-environment |
|---|---|---|---|---|
| `region` | `infra/terraform.tfvars` | string | `us-east-1` | Operator preference / data-residency |
| `project` | `infra/terraform.tfvars` | string | `opensre-demo` | Namespace-prefixes every resource; change to run two demos in one account |
| `db_password` | `infra/terraform.tfvars` (or `TF_VAR_db_password` env) | sensitive string | 24+ random chars | Secret; never commit |
| `ui_bucket_suffix` | `infra/terraform.tfvars` | string | `b71c4649` | S3 bucket names are **globally unique**; collisions fail the apply |
| `sut_ingress_cidr` | `infra/terraform.tfvars` | CIDR | `203.0.113.42/32` | Tighten to your egress IP for safety; `0.0.0.0/0` for open demos |
| `opensre_telegram_chat_id` | `infra/terraform.tfvars` | string | `-1001234567890` | Each operator has their own Telegram group |
| `opensre_host_enabled` | `infra/terraform.tfvars` | bool | `true` after Phase D | Toggle gates the OpenSRE EC2 + Lambda + FIS templates |
| `sut_desired_count` | `infra/terraform.tfvars` | number | `1` after Phase C | Toggle gates the ECS service starting the SUT task |
| Anthropic API key | AWS Secrets Manager `opensre/anthropic_api_key` | sensitive string | `sk-ant-...` | Per-operator API key |
| Telegram bot token | AWS Secrets Manager `opensre/telegram_bot_token` | sensitive string | `123456:ABC...` | Per-operator bot |
| AWS profile | shell env (`AWS_PROFILE`) | string | `default` | Selects credentials; never hard-coded |

**Rule of thumb:** if a value identifies *you* (account, IP, group, key), it lives in `terraform.tfvars` or Secrets Manager. The repo never sees it.

---

## Prerequisites

### Tooling on the operator workstation

| Tool | Min version | Verify | Notes |
|---|---|---|---|
| AWS CLI v2 | 2.7+ (FIS commands) | `aws --version` | v1 lacks `aws fis ...` |
| Session Manager plugin | latest | `session-manager-plugin --version` | For SSM port-forward to RDS |
| Terraform | 1.9.0+ | `terraform version` | `versions.tf` pins `~> 5.70` AWS provider |
| Docker (with buildx) | 24+ | `docker buildx version` | `--platform linux/amd64` is required on arm64 Macs |
| `uv` (Python tool) | 0.5+ | `uv --version` | Runs the seed script and backend tests |
| Node.js | 20+ | `node --version` | Builds the Next.js UI |
| `jq`, `uuidgen`, `base64` | any | `jq --version` | Used by helper scripts |

### AWS account requirements

The operator's IAM principal must be allowed to perform every action this stack creates. The simplest grant is an account-admin role for the duration of the demo. If using a least-privilege policy, it must include (non-exhaustive): `ec2:*`, `vpc:*`, `rds:*`, `ecs:*`, `ecr:*`, `s3:*`, `iam:*` (role + policy + instance-profile), `secretsmanager:*`, `ssm:*`, `cloudwatch:*`, `logs:*`, `lambda:*`, `sns:*`, `fis:*`, `application-autoscaling:*`, `kms:Decrypt`.

**Service quotas (defaults usually suffice):**
- 1× Elastic IP (default account quota: 5)
- 2× t3.micro instances (default: ~20 in `us-east-1`)
- 1× RDS db.t3.micro (default: 40)

**Cross-region note:** the AMI lookups use `data.aws_ssm_parameter` (ECS-optimised AL2023) and `data.aws_ami` filtered to Canonical Ubuntu 24.04 — both resolve per-region without code changes. Any region with EC2, RDS Postgres 16, FIS, and SSM RunCommand support works (i.e. all standard commercial regions).

### External accounts / services

1. **Anthropic API key.** Create at https://console.anthropic.com/. The OpenSRE host calls Claude for the RCA itself — kept entirely off the repo via Secrets Manager.
2. **Telegram bot.** Message [`@BotFather`](https://t.me/BotFather), `/newbot`, capture the token (format `123456:ABC...`).
3. **Telegram group.** Create a group, add the new bot **and** any downstream consumer bot (e.g. OpenClaw). Send any message in the group, then fetch the chat ID:
   ```bash
   curl -fsS "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[0].message.chat.id'
   # -> -1001234567890   (negative for groups; supergroups start with -100)
   ```

---

## Phase A — Configure for this environment

### A1 · Clone and inspect

```bash
git clone <repo-url> open-sre-agents
cd open-sre-agents
ls infra/terraform.tfvars.example     # template lives here
```

**Verify:** `infra/terraform.tfvars.example` exists. If it doesn't, the repo is at the wrong commit — pull `main`.

### A2 · Generate per-environment values

```bash
# Strong DB password — store this safely; you'll need it again to seed RDS in Phase C.
DB_PW=$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24)))')

# Random bucket suffix (S3 names are global). 8 hex chars is enough.
UI_SUFFIX=$(python3 -c 'import secrets; print(secrets.token_hex(4))')

echo "DB_PW=$DB_PW"
echo "UI_SUFFIX=$UI_SUFFIX"
```

**Verify:** Both variables print non-empty strings. Save them — they go into `terraform.tfvars` next.

### A3 · Author `infra/terraform.tfvars`

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
```

Then edit `infra/terraform.tfvars` so it looks like this (substitute your values):

```hcl
region                   = "us-east-1"
project                  = "opensre-demo"
db_password              = "<paste $DB_PW from A2>"
sut_ingress_cidr         = "0.0.0.0/0"           # tighten to <your-ip>/32 for safety
ui_bucket_suffix         = "<paste $UI_SUFFIX from A2>"
sut_desired_count        = 0                      # Phase B keeps this at 0
opensre_telegram_chat_id = "-1001234567890"       # your group chat ID
opensre_host_enabled     = false                  # Phase B keeps this at false
```

**Verify:** `git status` shows `infra/terraform.tfvars` as **untracked** (it must be — `infra/.gitignore` excludes it). If `git status` lists it as a tracked modification, stop and remove it from git: it was committed by mistake.

### A4 · Set the AWS profile

```bash
export AWS_PROFILE=<your-profile>      # or rely on default chain
aws sts get-caller-identity            # confirm Account, UserId, Arn match your operator identity
```

**Verify:** `Account` matches the AWS account you intend to deploy into. If not, fix `AWS_PROFILE` before proceeding — every subsequent step targets that account.

---

## Phase B — Bootstrap apply (cold infra)

This phase creates everything **except** the SUT ECS task and the OpenSRE EC2: VPC, RDS, ECR, S3, ECS cluster, IAM, Secrets Manager shells. The two toggles (`sut_desired_count = 0`, `opensre_host_enabled = false`) prevent the workloads from starting before their dependencies (image in ECR, secrets populated) exist.

### B1 · Initialize Terraform

```bash
cd infra
terraform init
```

**Verify:** Prints `Terraform has been successfully initialized!`. A `.terraform/` directory now exists.

### B2 · First apply (cold)

```bash
terraform apply
# Review the plan, then type "yes".
```

**Verify (must all be true before continuing):**

```bash
terraform output ecr_repository_url        # <acct>.dkr.ecr.<region>.amazonaws.com/opensre-demo-sut
terraform output rds_address               # opensre-demo-db.<id>.<region>.rds.amazonaws.com
terraform output sut_instance_id           # i-... (SUT EC2 host is up; ECS task is not — desired_count = 0)
terraform output anthropic_secret_id       # opensre/anthropic_api_key
terraform output telegram_secret_id        # opensre/telegram_bot_token
terraform output opensre_host_instance_id  # null  (correct — host_enabled = false)
```

Wait until `aws rds describe-db-instances --db-instance-identifier opensre-demo-db --query 'DBInstances[0].DBInstanceStatus' --output text` returns `available` (~5 min).

---

## Phase C — Backend image & seed data

### C1 · Build & push the SUT image

```bash
cd ..                                                # back to repo root
REGION=$(cd infra && terraform output -raw aws_region)
ECR_URL=$(cd infra && terraform output -raw ecr_repository_url)

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"

docker buildx build --platform linux/amd64 -t "$ECR_URL:latest" --load ./backend
docker push "$ECR_URL:latest"
```

**Why `--platform linux/amd64`:** the SUT EC2 is x86_64; arm64 Mac builds without this flag will refuse to start in ECS.

**Verify:**

```bash
aws ecr describe-images --region "$REGION" --repository-name opensre-demo-sut \
  --query 'imageDetails[0].imageTags' --output text
# -> latest
```

### C2 · Open an SSM port-forward to RDS

In a **separate** terminal (so it stays open while you seed):

```bash
SUT=$(cd infra && terraform output -raw sut_instance_id)
RDS=$(cd infra && terraform output -raw rds_address)
REGION=$(cd infra && terraform output -raw aws_region)

aws ssm start-session --region "$REGION" \
  --target "$SUT" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$RDS\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"15432\"]}"
```

**Why SSM port-forward:** RDS lives in private subnets with no public IP and no NAT; SSM proxies port 5432 through the SUT EC2 (which has SG allowing RDS access).

**Verify:** the session prints `Waiting for connections...`. Leave the terminal alone.

### C3 · Seed RDS to 10 000 rows

Back in the original terminal:

```bash
DB_PW=$(grep '^db_password' infra/terraform.tfvars | sed -E 's/.*= *"(.*)"/\1/')
SEED_DATABASE_URL="postgresql://opensre:${DB_PW}@localhost:15432/opensre_demo" \
  uv run scripts/seed_posts.py
```

**Verify:** prints `Seeded 10000 posts (table now has 10000).` (or `posts already has 10000 rows — skipping seed.` on a re-run; both are success).

Stop the port-forward terminal (Ctrl-C) once the seed completes.

---

## Phase D — Populate Secrets Manager

The OpenSRE host's user-data script reads these secrets on first boot and hard-fails if either is empty. **Populate before flipping `opensre_host_enabled = true`** in Phase E, or the bootstrap loops on a tainted instance.

### D1 · Anthropic API key

```bash
ANTHROPIC_SECRET=$(cd infra && terraform output -raw anthropic_secret_id)
read -rs -p "Anthropic API key: " AK && echo
aws secretsmanager put-secret-value \
  --secret-id "$ANTHROPIC_SECRET" \
  --secret-string "$AK" \
  --region "$REGION" >/dev/null
unset AK
```

### D2 · Telegram bot token

```bash
TELEGRAM_SECRET=$(cd infra && terraform output -raw telegram_secret_id)
read -rs -p "Telegram bot token: " TT && echo
aws secretsmanager put-secret-value \
  --secret-id "$TELEGRAM_SECRET" \
  --secret-string "$TT" \
  --region "$REGION" >/dev/null
unset TT
```

**Verify both:**

```bash
aws secretsmanager get-secret-value --secret-id "$ANTHROPIC_SECRET" --region "$REGION" \
  --query SecretString --output text | head -c 10 && echo "..."
# Expect: sk-ant-... (just the prefix; do not log the full value)
aws secretsmanager get-secret-value --secret-id "$TELEGRAM_SECRET" --region "$REGION" \
  --query SecretString --output text | head -c 8 && echo "..."
# Expect: a numeric prefix (bot ID) followed by ":" — e.g. "12345678:"
```

If either prints empty, repeat D1/D2.

---

## Phase E — Hot apply (SUT task + OpenSRE host)

### E1 · Flip both toggles

Edit `infra/terraform.tfvars`:

```diff
-sut_desired_count        = 0
+sut_desired_count        = 1
-opensre_host_enabled     = false
+opensre_host_enabled     = true
```

### E2 · Apply

```bash
cd infra && terraform apply
```

This replaces nothing and adds:
- ECS service (`desired_count = 1`) → starts the SUT task
- OpenSRE EC2 (`aws_instance.opensre[0]`) → user-data installs the OpenSRE CLI, sources secrets, posts a "hello" Telegram message, installs `python3 + httpx + /opt/opensre/load_runner.py`
- Lambda `opensre-demo-ingest-alarm` (depends on the OpenSRE instance ID)
- SNS subscription
- CloudWatch alarms `sut-cpu-saturation`, `sut-db-connection-errors`
- FIS service role + 2 experiment templates (`cpu-load-burst`, `rds-reboot`)

**Verify the SUT is healthy:**

```bash
SUT_API=$(terraform output -raw sut_api_url)
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "$SUT_API/health" >/dev/null 2>&1; then echo "SUT up after $i tries"; break; fi
  sleep 10
done
curl -fsS "$SUT_API/posts?limit=2" | jq '. | length'    # -> 2
```

**Verify SSM registers the OpenSRE host (~60 s):**

```bash
HOST=$(terraform output -raw opensre_host_instance_id)
for i in $(seq 1 24); do
  S=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$HOST" \
        --region "$REGION" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo Pending)
  echo "[$i] PingStatus: $S"; [ "$S" = "Online" ] && break; sleep 5
done
```

**Verify bootstrap completed (Telegram):** Open the configured Telegram group. A message starting `[OpenSRE bootstrap] host i-... online in <region>; ready for investigations.` must be present. **If it isn't**, see [Bootstrap fails](#bootstrap-fails-secret-empty-or-host-stuck-in-pending) below.

---

## Phase F — Deploy UI

```bash
cd ..   # repo root
./scripts/deploy_ui.sh
```

The script reads `terraform output` for `sut_api_url` and `ui_bucket`, builds the Next.js export with `NEXT_PUBLIC_API_URL` baked in, and `aws s3 sync`s `ui/out/` to the bucket.

**Verify:**

```bash
UI_URL=$(cd infra && terraform output -raw ui_website_url)
echo "$UI_URL"          # http://opensre-demo-ui-<suffix>.s3-website-<region>.amazonaws.com
curl -fsI "$UI_URL" | head -1     # HTTP/1.1 200 OK
```

Open `$UI_URL` in a browser. The PostsTable must render rows from RDS.

---

## Phase G — Verification gates

Each gate exercises one more layer of the chain. Run them in order; each one passing demonstrates the layer underneath also works.

### G1 · Synthetic alert → Telegram (Plan 2 layer)

```bash
./scripts/test_opensre_alert.sh
```

**Pass criteria:** script exits 0 with `Final status: Success`, and an RCA appears in the Telegram group within ~60 s of the script returning.

### G2 · Manually fired alarm → Telegram (Plan 3 layer)

```bash
ALARM_CPU=$(cd infra && terraform output -raw alarm_cpu_name)
aws cloudwatch set-alarm-state --region "$REGION" \
  --alarm-name "$ALARM_CPU" --state-value ALARM \
  --state-reason "build-runbook G2 smoke"
```

In another shell, watch the chain:

```bash
aws logs tail /aws/lambda/opensre-demo-ingest-alarm --since 2m --region "$REGION" --follow
# Expect: an "ssm:SendCommand sent" line within ~5 s of set-alarm-state.
```

**Pass criteria:** Lambda logs show one `SendCommand` invocation; an RCA appears in Telegram within ~3 min.

Repeat for the DB alarm:

```bash
ALARM_DB=$(cd infra && terraform output -raw alarm_db_errors_name)
aws cloudwatch set-alarm-state --region "$REGION" \
  --alarm-name "$ALARM_DB" --state-value ALARM \
  --state-reason "build-runbook G2 db smoke"
```

### G3 · FIS chaos → Telegram (Plan 5 layer; the MVP success criterion)

```bash
./scripts/start_chaos.sh cpu --follow
# Ctrl-C the tail when "opensre investigate" finishes and the RCA hits Telegram.
```

**Pass criteria:** within ~3.5 min of the script printing `experiment: EXP...`, the SUT instance EC2 `CPUUtilization` exceeds 50 %, the `sut-cpu-saturation` alarm transitions OK→ALARM, the Lambda fires, and an RCA arrives in Telegram citing realistic traffic evidence (mixed endpoint paths, varied source IPs from `203.0.113.X`).

```bash
./scripts/start_chaos.sh rds
# Drive a small amount of traffic so connection failures appear in the SUT log group:
SUT_API=$(cd infra && terraform output -raw sut_api_url)
for _ in 1 2 3 4 5 6; do curl -fsS "$SUT_API/posts?limit=1" || true; sleep 3; done
```

**Pass criteria:** `ConnectionRefusedError` log lines appear in `/ecs/opensre-demo-sut`, the `sut-db-connection-errors` metric filter increments, the alarm transitions, an RCA arrives in Telegram citing `[Errno 111]` and recommending DB-status / container-restart actions.

If G1, G2, and G3 all pass, the build is complete and matches the spec §11 success criterion.

---

## Teardown

The teardown is *one* `terraform destroy` plus pre-flight checks. The Terraform resources are deliberately configured so destroy succeeds without manual cleanup:

- `aws_ecr_repository.sut` has `force_delete = true` → destroys with images.
- `aws_s3_bucket.ui` has `force_destroy = true` → destroys with objects.
- `aws_secretsmanager_secret.{anthropic,telegram}` have `recovery_window_in_days = 0` → destroyed immediately, no scheduled deletion.
- `aws_db_instance.demo` has `skip_final_snapshot = true`.

### T1 · Stop in-flight chaos experiments

```bash
REGION=$(cd infra && terraform output -raw aws_region)
aws fis list-experiments --region "$REGION" \
  --query 'experiments[?contains(state.status, `running`) || contains(state.status, `pending`) || contains(state.status, `initiating`)].[id,state.status]' \
  --output text
```

If the list is non-empty, stop each:

```bash
aws fis stop-experiment --region "$REGION" --id <experiment-id>
```

Then re-run `list-experiments` to confirm all are in a terminal state (`completed`, `stopped`, `failed`).

**Why:** `terraform destroy` will refuse to delete the FIS templates while an experiment using them is still running.

### T2 · (Optional) Reduce blast radius before destroy

For a cautious teardown, flip the gates first to remove the Lambda, OpenSRE host, and FIS templates *before* destroying the foundation. This isolates any failure to one layer:

```hcl
# infra/terraform.tfvars
sut_desired_count        = 0
opensre_host_enabled     = false
```

```bash
cd infra && terraform apply
```

This destroys the OpenSRE EC2, the Lambda (which depends on `aws_instance.opensre[0].id`), the SNS subscription, and the FIS templates (which depend on `aws_instance.opensre`). Plan-1 foundation remains.

If you skip T2, T3 still works — `terraform destroy` orders deletions correctly via the dependency graph. Use T2 only when troubleshooting a partial-destroy.

### T3 · Destroy

```bash
cd infra
terraform destroy
# Review the plan (expect ~50–60 resources to be destroyed), type "yes".
```

**Verify (zero results expected for each):**

```bash
aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Project,Values=opensre-demo" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text
# -> empty

aws rds describe-db-instances --region "$REGION" \
  --query "DBInstances[?DBInstanceIdentifier=='opensre-demo-db'].DBInstanceIdentifier" --output text
# -> empty

aws s3api list-buckets \
  --query "Buckets[?starts_with(Name, 'opensre-demo-ui-')].Name" --output text
# -> empty

aws ecr describe-repositories --region "$REGION" \
  --query "repositories[?repositoryName=='opensre-demo-sut'].repositoryName" --output text
# -> empty

aws secretsmanager list-secrets --region "$REGION" \
  --query "SecretList[?starts_with(Name, 'opensre/')].Name" --output text
# -> empty (recovery_window=0 means immediate)

aws fis list-experiment-templates --region "$REGION" \
  --query 'experimentTemplates[?contains(tags.Project, `opensre-demo`)].id' --output text
# -> empty

aws lambda list-functions --region "$REGION" \
  --query "Functions[?starts_with(FunctionName, 'opensre-demo-')].FunctionName" --output text
# -> empty

aws cloudwatch describe-alarms --region "$REGION" \
  --alarm-name-prefix sut- --query 'MetricAlarms[].AlarmName' --output text
# -> empty

aws ec2 describe-vpcs --region "$REGION" \
  --filters "Name=tag:Project,Values=opensre-demo" \
  --query 'Vpcs[].VpcId' --output text
# -> empty

aws ec2 describe-addresses --region "$REGION" \
  --filters "Name=tag:Project,Values=opensre-demo" \
  --query 'Addresses[].AllocationId' --output text
# -> empty   (releases the EIP — billed if left attached to no instance)
```

If any of these returns a non-empty value, see [Destroy left orphans](#destroy-left-orphans).

### T4 · Local cleanup (operator workstation)

```bash
cd infra
rm -rf .terraform .terraform.lock.hcl terraform.tfstate terraform.tfstate.backup terraform.tfvars build/
cd ..
```

### T5 · Off-AWS cleanup (optional)

- Revoke the Anthropic API key in https://console.anthropic.com/ if no longer needed.
- Revoke / delete the Telegram bot via `@BotFather → /mybots → API Token → Revoke` (only if the bot is single-purpose for this demo).

---

## Portability checklist

Run through this list when adapting the demo to a new account, region, or operator. Anything not listed is portable by construction (resource names derive from `${var.project}`, AMI lookups are region-agnostic, IAM policies reference `data.aws_caller_identity.current.account_id`).

- [ ] `region` set in `terraform.tfvars` matches the AWS region you intend to use.
- [ ] `AWS_PROFILE` (or default credentials chain) points at the target account; `aws sts get-caller-identity` confirms.
- [ ] `db_password` regenerated (do **not** reuse a previous environment's value).
- [ ] `ui_bucket_suffix` regenerated (S3 names are global; old suffixes from another environment are still owned by the previous account and will collide).
- [ ] `sut_ingress_cidr` set to `0.0.0.0/0` (open demo) or `<your-ip>/32` (restricted).
- [ ] `opensre_telegram_chat_id` is **this** operator's group (the message format is operator-specific; cross-posting to a shared group will confuse downstream consumers).
- [ ] Anthropic API key populated for **this** account's `opensre/anthropic_api_key` secret.
- [ ] Telegram bot token populated for **this** account's `opensre/telegram_bot_token` secret. The bot **must** be a member of the group whose ID is in `opensre_telegram_chat_id`.
- [ ] Account quotas: 1 EIP, 2 t3.micros, 1 RDS db.t3.micro available (raise via Service Quotas if necessary).
- [ ] If you renamed `var.project` from the default `opensre-demo`, confirm the helper scripts you invoke are using outputs (they are — they read `terraform output -raw aws_region`, `sut_instance_id`, etc., so renaming is safe). The hard-coded names you'll see in the helper scripts (`/aws/lambda/opensre-demo-ingest-alarm`, `/ecs/opensre-demo-sut`) are runtime-only — fix them in the scripts if you change `var.project`.
- [ ] (Optional) Configure a remote Terraform backend (S3 + DynamoDB) before `terraform init` if multiple operators will share state. The local backend default is fine for a single-operator demo.

---

## Failure modes & recovery

### Bootstrap fails (secret empty or host stuck in Pending)

**Symptom:** Phase E `terraform apply` succeeds, `opensre_host_instance_id` returns an EC2 ID, but `aws ssm describe-instance-information` keeps returning empty after >2 min, **or** the SSM call works but no `[OpenSRE bootstrap]` Telegram message arrives.

**Root cause:** the user-data script aborted because one of the secrets was empty when the EC2 first booted. It does not retry.

**Recovery:**

```bash
# 1. Confirm both secrets have non-empty values (Phase D verification commands).
# 2. Force a fresh boot of the OpenSRE host:
cd infra
terraform taint 'aws_instance.opensre[0]'
terraform apply
# 3. Wait ~90 s. Re-run the SSM/PingStatus check from Phase E.
# 4. Inspect the bootstrap log if it still fails:
HOST=$(terraform output -raw opensre_host_instance_id)
aws ssm send-command --region "$REGION" --instance-ids "$HOST" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["tail -100 /var/log/opensre-bootstrap/bootstrap.log"]' \
  --query 'Command.CommandId' --output text
# Then aws ssm get-command-invocation ... once the command completes.
```

### ECS service stuck `pending`

**Symptom:** Phase E `terraform apply` succeeds but `curl $sut_api_url/health` keeps timing out and `aws ecs describe-services` shows `runningCount: 0`, `desiredCount: 1`, `pendingCount: 1`.

**Root cause:** the ECS-optimized AMI on the SUT EC2 hasn't joined the cluster yet, **or** the image push in Phase C didn't actually upload `:latest`.

**Recovery:**

```bash
# Check whether the EC2 host registered:
aws ecs list-container-instances --cluster opensre-demo --region "$REGION"

# Check the image actually exists:
aws ecr describe-images --repository-name opensre-demo-sut --region "$REGION" \
  --query 'imageDetails[].imageTags' --output json

# Force-roll the service (it'll re-pull):
aws ecs update-service --region "$REGION" --cluster opensre-demo \
  --service opensre-demo-sut --force-new-deployment >/dev/null
```

### S3 bucket name collision

**Symptom:** Phase B `terraform apply` fails with `BucketAlreadyExists` on `aws_s3_bucket.ui`.

**Root cause:** `ui_bucket_suffix` collides with another bucket somewhere in S3 (global namespace).

**Recovery:** generate a new `ui_bucket_suffix` (Phase A2 command) and re-apply.

### Destroy left orphans

**Symptom:** Teardown verification shows non-empty results.

**Recovery (most common cases):**

```bash
# CW Logs groups can persist if an out-of-band write happened during destroy.
aws logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix /ecs/opensre-demo \
  --query 'logGroups[].logGroupName' --output text \
  | xargs -n1 aws logs delete-log-group --region "$REGION" --log-group-name

aws logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix /aws/lambda/opensre-demo \
  --query 'logGroups[].logGroupName' --output text \
  | xargs -n1 aws logs delete-log-group --region "$REGION" --log-group-name

aws logs delete-log-group --region "$REGION" --log-group-name /aws/ssm/opensre-investigate || true

# Orphan EIP (rare — happens if instance deletion races):
aws ec2 describe-addresses --region "$REGION" \
  --filters "Name=tag:Name,Values=opensre-demo-sut-eip" \
  --query 'Addresses[].AllocationId' --output text \
  | xargs -n1 aws ec2 release-address --region "$REGION" --allocation-id
```

If the VPC itself remains, a manual `aws ec2 delete-vpc` is rarely safe — re-import into Terraform via `terraform import aws_vpc.main <vpc-id>` and re-run `terraform destroy` instead.

### FIS experiment hangs / `terraform destroy` blocks on FIS template

**Symptom:** `terraform destroy` hangs on `aws_fis_experiment_template.cpu_load_burst` or `.rds_reboot`.

**Recovery:** see [T1](#t1--stop-in-flight-chaos-experiments). Stop the experiment, then re-run destroy.

### `ssm start-session` reports `TargetNotConnected`

**Symptom:** Phase C C2 fails immediately.

**Root cause:** the SUT EC2 has booted but the SSM agent hasn't yet phoned home (~60 s grace period after instance boot, longer in some regions).

**Recovery:** wait 60 s and retry. If still failing, confirm the SUT host's IAM role has `AmazonSSMManagedInstanceCore` attached (it does by default in `infra/ecs.tf`; only an out-of-band edit would remove it).

---

## Time & cost budget

**Time-on-task (greenfield account, operator familiar with the steps):**

| Phase | Wall-clock |
|---|---|
| A — Configure | 5–10 min (most spent on Telegram bot/group setup if first-time) |
| B — Cold apply | 5–8 min (RDS create dominates) |
| C — Image + seed | 4–6 min |
| D — Secrets | <1 min |
| E — Hot apply | 3–5 min (OpenSRE host bootstrap is ~90 s of that) |
| F — UI deploy | 1–2 min |
| G — Verification | 8–12 min (three smoke tests, each ~3 min for the agent's RCA) |
| **Total build** | **~30–45 min** |
| Teardown (T1–T3) | 5–8 min |

**Cost (us-east-1, AWS Free Tier eligible account):**

| Resource | Cost while running | Free Tier? |
|---|---|---|
| 2× t3.micro EC2 (SUT + OpenSRE host) | ~$0.0104/hr each | First t3.micro free up to 750 hr/month; second is ~$7.50/mo if always-on |
| RDS db.t3.micro (single-AZ, 20 GB gp3) | ~$0.018/hr | First 750 hr/mo free for 12 mo of new accounts |
| S3 (UI hosting) | <$0.01/mo | Free Tier covers <5 GB |
| ECR (single image, ~150 MB) | <$0.02/mo | Free Tier 500 MB |
| CW Logs (4 log groups, 7-day retention) | <$0.10/mo | First 5 GB ingest free |
| CW Alarms (2) | $0.20/mo | First 10 alarms free |
| FIS experiments | $0.10/action-min, billed on declared `duration`. CPU template = 4 min × 2 actions = $0.80; RDS template = ~$0.05 | None |
| Lambda + SNS | <$0.01/mo (dozens of invocations) | Free Tier covers millions |
| Anthropic API | ~$0.03–$0.10 per RCA (Sonnet 4.6) | None — per-token |
| **All-up steady-state, demo idle** | **~$8–12/mo** if both EC2s exceed Free Tier | — |
| **Per chaos experiment** | **~$0.50** (FIS + Anthropic) | — |

**Cost-control tips:**
- Tear down between demo sessions if you don't need always-on. Re-build takes ~30 min.
- Or flip `opensre_host_enabled = false` and `sut_desired_count = 0` (Phase T2) to keep the foundation up but stop the workload — saves ~$8/mo at the cost of ~5 min to re-warm.
- Set CW Logs retention shorter than 7 days if you do many experiments (already `retention_in_days = 7` in Terraform — fine for the demo cadence).

---

## Appendix: re-applying after a partial failure

If `terraform apply` errors mid-way:

1. Re-read the error. Most failures are: secret-name collision (another stack already owns `opensre/anthropic_api_key`), bucket-name collision (regenerate `ui_bucket_suffix`), or quota (raise it).
2. Fix the underlying cause.
3. Re-run `terraform apply`. Terraform retries the failed resource and continues. State is consistent — no manual state edits should be necessary.

For a *clean slate* mid-build:

```bash
cd infra && terraform destroy   # accept any prompts
# Fix tfvars / quota / collision
terraform apply
```

The two-phase toggle pattern (Phases B and E) means a failed apply at any step can be retried after toggling back to the cold state (`opensre_host_enabled = false`, `sut_desired_count = 0`) and re-applying — the cold state is always reachable.
