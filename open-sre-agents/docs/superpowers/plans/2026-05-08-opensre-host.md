# OpenSRE MVP — Plan 2: OpenSRE Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the long-lived OpenSRE EC2 host that runs `opensre investigate` against synthetic alerts and posts RCAs to a **Telegram group** (where a downstream **OpenClaw bot** picks up the RCA reports as input). This adds the **agent layer** to the demo backbone delivered in Plan 1; nothing yet automatically routes CloudWatch alarms here (that lands in Plan 3). End state: the operator can SSM-RunCommand a synthetic alert JSON to the host and watch a real RCA appear in the configured Telegram group.

**Architecture:** A second `t3.micro` EC2 (separate from the SUT, in `public_a`) runs Amazon Linux 2023 with the SSM agent and the OpenSRE CLI. User-data installs `opensre` via `curl -fsSL https://install.opensre.com | bash`, fetches `ANTHROPIC_API_KEY` + `TELEGRAM_BOT_TOKEN` from AWS Secrets Manager, writes `/etc/opensre/.env` with those plus `TELEGRAM_DEFAULT_CHAT_ID` (per https://opensre.com/docs/messaging/telegram.md), runs `opensre integrations verify` to confirm Anthropic + Telegram are reachable (the Telegram check uses Telegram's `getMe` endpoint), and posts a "hello" sanity message via direct curl to confirm the chat ID is right. **No wrapper script** — `opensre investigate` posts to Telegram natively via OpenSRE's built-in messaging integration (truncated at 4 096 chars per Telegram per-message limit). Read-only AWS permissions per OpenSRE's documented requirements + narrowly-scoped read on the two named secrets. CloudWatch Logs receive SSM RunCommand stdout/stderr from every `opensre investigate` invocation. A `var.opensre_host_enabled` toggle gates the EC2 itself so the operator can populate secrets between two applies.

**Tech Stack:** Terraform 1.9+ with AWS provider 5.x · Amazon Linux 2023 · OpenSRE CLI (with built-in Telegram messaging integration) · Anthropic Claude (default `claude-sonnet-4-6`) · AWS Secrets Manager · AWS SSM RunCommand · CloudWatch Logs · bash · session-manager-plugin

---

## Prerequisites

Plan 1 must be applied. Confirm:

```bash
cd infra && terraform output sut_api_url               # prints a URL
curl -fsS "$(cd infra && terraform output -raw sut_api_url)/health"
# {"status":"ok"}
```

You also need:
- **Anthropic API key.** Create at https://console.anthropic.com/settings/keys. Format `sk-ant-…`. Keep it; you'll paste once.
- **Telegram bot.** Open Telegram → message `@BotFather` → `/newbot` → follow prompts → capture the bot token (format `123456789:ABCdef…`, ~46 chars). Save it; you'll paste once.
- **Telegram group + chat ID.** Create a Telegram group (any name). **Add the OpenSRE bot to it** (group settings → Add member → search `@<your_bot_username>`). **Add the OpenClaw bot** to the same group (it will be the downstream consumer of RCAs). Get the chat ID by either:
  - **Easiest:** add `@RawDataBot` (or `@userinfobot`) to the group, send any message; the bot replies with the group's chat ID (e.g. `-1001234567890` — note the leading `-` for groups). Remove the helper bot.
  - **Manual:** send any message in the group, then `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[].message.chat.id'`. The first negative number is your group chat ID.
- **OpenClaw bot** in the group (downstream consumer). Out of scope for this plan beyond presence — just confirm it's there and ready to receive messages. If OpenClaw needs the bot's Telegram privacy mode disabled to read other bots' messages, set that with BotFather: `/mybots → <openclaw_bot> → Bot Settings → Group Privacy → Turn off`. (This affects OpenClaw, not the OpenSRE bot.)
- **`session-manager-plugin`** locally — install per https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html. Verify with `session-manager-plugin --version`.
- **`uuidgen`** locally — preinstalled on macOS; on Linux: `apt install uuid-runtime`.

**Smoke-test the bot before running this plan** (catches token/chat-id mistakes early):

```bash
read -rs -p "Telegram bot token: " TG_TOKEN && echo
read -p   "Telegram chat ID:    " TG_CHAT
curl -sS -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TG_CHAT}" \
  --data-urlencode "text=opensre-host bootstrap precheck — if you see this, the bot+chat-id work."
unset TG_TOKEN
```

Expected: a message appears in your Telegram group, and the curl response is `{"ok":true,...}`. If `{"ok":false,"error_code":403,...}`, the bot isn't in the group; if `400 chat not found`, the chat ID is wrong.

**Doc-verification gate.** OpenSRE is an evolving platform; CLI install URL and integration setup may have shifted since spec drafting. **Before Tasks 2 (user_data script) and 7 (integrations verify), confirm via https://opensre.com/docs/install.md and https://opensre.com/docs/messaging/telegram.md that:**

- The install command is still `curl -fsSL https://install.opensre.com | bash`.
- The Telegram env vars are still `TELEGRAM_BOT_TOKEN` + `TELEGRAM_DEFAULT_CHAT_ID`.
- `opensre integrations verify telegram` exists and validates the bot token via Telegram's `getMe` endpoint.
- `opensre investigate -i <alert.json>` runs an investigation from a JSON file.
- Whether `opensre investigate` requires `opensre onboard` to have completed first, or whether env vars alone are sufficient. **This is the most important unknown.** If `onboard` is required and only interactive, the user-data script's "Step 5" below (smoke test) will fail with a "telegram not configured" or similar error — the recovery path is documented in `opensre_host/README.md` (Task 9): SSM-Session into the host and run `opensre onboard` interactively, then re-run the smoke test.

Per CLAUDE.md, always check current docs before acting. Update the user-data script accordingly *before* applying.

---

## File Structure

Files this plan creates:

```
open-sre-agents/
├── infra/
│   ├── secrets.tf                       # NEW: Secrets Manager shells (anthropic + telegram_bot_token)
│   ├── opensre_host.tf                  # NEW: IAM role + instance profile + SG + EC2 + EIP-less host
│   └── ssm_logs.tf                      # NEW: CloudWatch log group for SSM RunCommand output
├── opensre_host/
│   ├── user_data.sh.tftpl               # NEW: Terraform-templated bootstrap script
│   └── README.md                        # NEW: how to inspect / re-run bootstrap / debug
└── scripts/
    └── test_opensre_alert.sh            # NEW: send a synthetic alert via SSM and poll status
```

Files this plan modifies:

```
open-sre-agents/
├── infra/
│   ├── variables.tf                     # add opensre_telegram_chat_id + opensre_host_enabled
│   └── outputs.tf                       # add anthropic/telegram secret IDs + opensre host outputs
├── infra/terraform.tfvars.example       # add opensre_telegram_chat_id + opensre_host_enabled
└── README.md                            # add Plan 2 quick-start section
```

**Why these files:** each Terraform file owns one responsibility (secrets / host / SSM logs) so destroy/recreate cycles stay surgical. The bootstrap script lives outside `infra/` because it isn't Terraform — it's the *contents* templated into `aws_instance.opensre.user_data`. The helper script lives in `scripts/` next to the Plan-1 `seed_posts.py` and `deploy_ui.sh`.

---

## Task 1: Secrets Manager shells + variable + outputs

**Files:**
- Create: `infra/secrets.tf`
- Modify: `infra/variables.tf` (append two variables at end)
- Modify: `infra/outputs.tf` (append two outputs at end)
- Modify: `infra/terraform.tfvars.example` (append two lines)

- [ ] **Step 1: Create `infra/secrets.tf`**

```terraform
# Empty Secrets Manager shells. Values are populated manually after the first
# `terraform apply` via `aws secretsmanager put-secret-value` so credentials
# never enter the repo or terraform state files.

resource "aws_secretsmanager_secret" "anthropic" {
  name                    = "opensre/anthropic_api_key"
  description             = "OpenSRE host: Anthropic API key for the agent's LLM calls."
  recovery_window_in_days = 0 # demo: allow immediate recreation on destroy
  tags                    = { Name = "${var.project}-anthropic-api-key" }
}

resource "aws_secretsmanager_secret" "telegram" {
  name                    = "opensre/telegram_bot_token"
  description             = "OpenSRE host: Telegram bot token for posting RCA messages via Bot API."
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project}-telegram-bot-token" }
}
```

- [ ] **Step 2: Append to `infra/variables.tf`**

Open `infra/variables.tf` and add at the end of the file:

```terraform
variable "opensre_telegram_chat_id" {
  description = "Telegram chat ID for the group OpenSRE posts RCAs to (e.g., -1001234567890). Bot must be added to this group. Non-secret, but required."
  type        = string
}

variable "opensre_host_enabled" {
  description = "Set to false on the first apply (creates secret shells only) and true after secrets are populated (creates the EC2)."
  type        = bool
  default     = false
}
```

- [ ] **Step 3: Append to `infra/outputs.tf`**

Open `infra/outputs.tf` and add at the end of the file:

```terraform
output "anthropic_secret_id" {
  description = "Run: aws secretsmanager put-secret-value --secret-id <this> --secret-string sk-ant-..."
  value       = aws_secretsmanager_secret.anthropic.id
}

output "telegram_secret_id" {
  description = "Run: aws secretsmanager put-secret-value --secret-id <this> --secret-string <bot-token>"
  value       = aws_secretsmanager_secret.telegram.id
}

output "aws_region" {
  description = "Region resolved from var.region. Helper scripts read this output."
  value       = var.region
}
```

- [ ] **Step 4: Append to `infra/terraform.tfvars.example`**

```text
opensre_telegram_chat_id = "-1001234567890"   # replace with your group's chat ID (negative number for groups)
opensre_host_enabled     = false              # flip to true after Secrets Manager values are populated (Plan 2 Task 5)
```

- [ ] **Step 5: Validate Terraform**

Run: `cd infra && terraform fmt && terraform validate`
Expected output:
```
Success! The configuration is valid.
```

- [ ] **Step 6: Plan to verify the change**

Run: `cd infra && terraform plan -out=plan-secrets.tfplan`
Expected: plan shows `2 to add, 0 to change, 0 to destroy` for the two `aws_secretsmanager_secret` resources, plus three new outputs. **Do not apply yet** — Tasks 2–4 add more resources to the same apply.

- [ ] **Step 7: Commit**

```bash
git add infra/secrets.tf infra/variables.tf infra/outputs.tf infra/terraform.tfvars.example
git commit -m "feat(infra): add Secrets Manager shells for OpenSRE host"
rm -f infra/plan-secrets.tfplan
```

---

## Task 2: User-data bootstrap script

**Files:**
- Create: `opensre_host/user_data.sh.tftpl`

This is a Terraform template (`.tftpl`) — Terraform's `templatefile()` function substitutes `${opensre_telegram_chat_id}` at apply time. All bash variables use `$VAR` form (no curly braces) to avoid colliding with Terraform interpolation syntax. There is **no** wrapper script — `opensre investigate` posts to Telegram via OpenSRE's built-in messaging integration once `TELEGRAM_BOT_TOKEN` and `TELEGRAM_DEFAULT_CHAT_ID` are present in the environment.

- [ ] **Step 1: Create `opensre_host/` directory**

```bash
mkdir -p opensre_host
```

- [ ] **Step 2: Create `opensre_host/user_data.sh.tftpl`**

```bash
#!/bin/bash
# OpenSRE host bootstrap. Runs once on EC2 first boot.
#
# Logs:   /var/log/opensre-bootstrap/bootstrap.log
# Marker: /var/log/opensre-bootstrap/bootstrap.ok (touched only on success)
#
# Recovery if this fails (typically because secrets are still empty):
#   cd infra && terraform taint 'aws_instance.opensre[0]' && terraform apply

set -euo pipefail

LOG_DIR=/var/log/opensre-bootstrap
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/bootstrap.log") 2>&1
echo "[$(date -u +%FT%TZ)] OpenSRE host bootstrap starting"

# --- IMDSv2 token (required on AL2023) ---
TOKEN=$(curl -fsS -X PUT \
  "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
REGION=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/placement/region)
export AWS_DEFAULT_REGION="$REGION"
echo "Region: $AWS_DEFAULT_REGION"

# AL2023 ships curl + aws-cli; install jq for the smoke-test response check.
dnf install -y jq

# --- 1. Install opensre CLI (URL per https://opensre.com/docs/install.md) ---
echo "[$(date -u +%FT%TZ)] Installing opensre CLI..."
curl -fsSL https://install.opensre.com | bash
export PATH="/usr/local/bin:$PATH"
opensre --version

# --- 2. Fetch secrets via instance role ---
echo "[$(date -u +%FT%TZ)] Fetching secrets..."
ANTHROPIC_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id opensre/anthropic_api_key \
  --query SecretString --output text)
TELEGRAM_BOT_TOKEN=$(aws secretsmanager get-secret-value \
  --secret-id opensre/telegram_bot_token \
  --query SecretString --output text)

if [ -z "$ANTHROPIC_API_KEY" ] || [ "$ANTHROPIC_API_KEY" = "None" ]; then
  echo "FATAL: opensre/anthropic_api_key is empty. Populate it via:" >&2
  echo "  aws secretsmanager put-secret-value --secret-id opensre/anthropic_api_key --secret-string sk-ant-..." >&2
  exit 1
fi
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ "$TELEGRAM_BOT_TOKEN" = "None" ]; then
  echo "FATAL: opensre/telegram_bot_token is empty. Populate it via:" >&2
  echo "  aws secretsmanager put-secret-value --secret-id opensre/telegram_bot_token --secret-string '<bot-token>'" >&2
  exit 1
fi

# --- 3. Write env file ---
# OpenSRE's built-in Telegram messaging reads TELEGRAM_BOT_TOKEN +
# TELEGRAM_DEFAULT_CHAT_ID per https://opensre.com/docs/messaging/telegram.md.
# A system-wide profile snippet exports the same vars into every interactive
# shell so SSM Session Manager invocations also pick them up.
echo "[$(date -u +%FT%TZ)] Writing /etc/opensre/.env..."
mkdir -p /etc/opensre
umask 077
cat > /etc/opensre/.env <<ENVEOF
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_DEFAULT_CHAT_ID=${opensre_telegram_chat_id}
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
AWS_REGION=$REGION
ENVEOF
chmod 600 /etc/opensre/.env

# Make the env file source-able for any future shell on the box (root + ssm-user).
cat > /etc/profile.d/opensre.sh <<'PROFILE'
# Auto-source OpenSRE env vars for interactive shells.
if [ -f /etc/opensre/.env ]; then
  set -a
  . /etc/opensre/.env
  set +a
fi
PROFILE
chmod 644 /etc/profile.d/opensre.sh

# --- 4. Source for this script + verify integrations ---
set -a; . /etc/opensre/.env; set +a

echo "[$(date -u +%FT%TZ)] Running opensre integrations verify..."
# Per https://opensre.com/docs/messaging/telegram.md, `... verify telegram`
# validates the bot token via Telegram's getMe endpoint. Plain `... verify`
# checks every integration including Anthropic.
opensre integrations verify

# --- 5. Telegram smoke message via direct curl (proves token + chat ID work) ---
# OpenSRE itself only posts as part of an investigation, so we use a one-off
# curl here to confirm the bot is in the group and the chat ID resolves.
echo "[$(date -u +%FT%TZ)] Posting Telegram bootstrap smoke message..."
HOST_ID=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/instance-id)
curl -fsS -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
  --data-urlencode "chat_id=$TELEGRAM_DEFAULT_CHAT_ID" \
  --data-urlencode "text=[OpenSRE bootstrap] host $HOST_ID online in $REGION; ready for investigations." \
  --data-urlencode "disable_web_page_preview=true" \
  | jq -e '.ok' >/dev/null

echo "[$(date -u +%FT%TZ)] OpenSRE host bootstrap complete"
touch "$LOG_DIR/bootstrap.ok"
```

**Note on Terraform escaping:** the only `${...}` token in this script is `${opensre_telegram_chat_id}` — that's the Terraform variable, expanded at apply time. The inner single-quoted heredoc (`<<'PROFILE'`) is plain bash (no Terraform vars inside), so no `$${...}` escaping is needed.

**Note on `opensre onboard`:** OpenSRE's interactive `onboard` command writes credentials into a config file. The docs (https://opensre.com/docs/messaging/telegram.md) describe configuration via env vars only, and `opensre integrations verify` is the canonical health-check; we therefore skip `onboard` in user-data. If the bootstrap smoke (Step 5 above OR `integrations verify` failing) reveals that env-vars-only doesn't suffice in your OpenSRE version, the recovery path is documented in `opensre_host/README.md` (Task 9): SSM-Session into the host, run `opensre onboard` interactively, retry.

- [ ] **Step 3: Lint the bash script**

Run: `bash -n opensre_host/user_data.sh.tftpl`
Expected: no output (no syntax errors). The Terraform `${opensre_telegram_chat_id}` token doesn't trip bash's parser at this stage — `bash -n` doesn't expand variables.

If you have `shellcheck` installed: `shellcheck -e SC1083 opensre_host/user_data.sh.tftpl` (the `-e SC1083` suppresses the warning about the Terraform `${...}` token).

- [ ] **Step 4: Commit**

```bash
git add opensre_host/user_data.sh.tftpl
git commit -m "feat(opensre-host): add user-data bootstrap script"
```

---

## Task 3: OpenSRE host Terraform — IAM, security group, EC2 instance

**Files:**
- Create: `infra/opensre_host.tf`
- Modify: `infra/outputs.tf` (append `opensre_host_instance_id`)

- [ ] **Step 1: Create `infra/opensre_host.tf`**

```terraform
# OpenSRE EC2 host — deliberately separate from the SUT host so chaos
# targeting the SUT can't take down the agent layer. SSM-only access; no
# inbound SG. Gated by var.opensre_host_enabled so secrets can be populated
# between the first apply (false) and the EC2 boot (true).

# --- IAM: assume-role for EC2 ---
data "aws_iam_policy_document" "opensre_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "opensre_host" {
  name               = "${var.project}-opensre-host"
  assume_role_policy = data.aws_iam_policy_document.opensre_assume.json
}

# Managed: SSM RunCommand + Session Manager target.
resource "aws_iam_role_policy_attachment" "opensre_ssm" {
  role       = aws_iam_role.opensre_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Inline: read-only AWS for OpenSRE's investigation calls (per spec §4 IAM).
data "aws_iam_policy_document" "opensre_readonly" {
  statement {
    sid    = "AwsReadOnlyForInvestigation"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "ecs:Describe*",
      "ecs:List*",
      "rds:DescribeDBInstances",
      "rds:DescribeEvents",
      "cloudwatch:GetMetricData",
      "cloudwatch:ListMetrics",
      "logs:FilterLogEvents",
      "logs:GetLogEvents",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "opensre_readonly" {
  name   = "${var.project}-opensre-readonly"
  role   = aws_iam_role.opensre_host.id
  policy = data.aws_iam_policy_document.opensre_readonly.json
}

# Inline: read the two named secrets only.
data "aws_iam_policy_document" "opensre_secrets" {
  statement {
    sid     = "ReadDemoSecrets"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.anthropic.arn,
      aws_secretsmanager_secret.telegram.arn,
    ]
  }
}

resource "aws_iam_role_policy" "opensre_secrets" {
  name   = "${var.project}-opensre-secrets"
  role   = aws_iam_role.opensre_host.id
  policy = data.aws_iam_policy_document.opensre_secrets.json
}

resource "aws_iam_instance_profile" "opensre_host" {
  name = "${var.project}-opensre-host"
  role = aws_iam_role.opensre_host.name
}

# --- Security group: outbound only ---
resource "aws_security_group" "opensre_host" {
  name        = "${var.project}-opensre-host"
  description = "OpenSRE host: outbound only; SSM-managed (no inbound)."
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All egress (AWS APIs + Anthropic + api.telegram.org)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-opensre-host" }
}

# --- AMI: AL2023 standard (not ECS-optimised; this host doesn't run containers) ---
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# --- EC2 host (gated by var.opensre_host_enabled) ---
resource "aws_instance" "opensre" {
  count = var.opensre_host_enabled ? 1 : 0

  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.opensre_host.id]
  iam_instance_profile   = aws_iam_instance_profile.opensre_host.name

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1
  }

  user_data = templatefile("${path.module}/../opensre_host/user_data.sh.tftpl", {
    opensre_telegram_chat_id = var.opensre_telegram_chat_id
  })

  # If user_data changes, replace the instance so the new bootstrap runs.
  user_data_replace_on_change = true

  tags = {
    Name    = "${var.project}-opensre-host"
    Project = var.project
    Role    = "opensre-agent"
  }

  # Make sure the secret shells exist (so the IAM policy ARNs resolve) before
  # the EC2 boots and tries to read them.
  depends_on = [
    aws_secretsmanager_secret.anthropic,
    aws_secretsmanager_secret.telegram,
    aws_iam_role_policy.opensre_secrets,
    aws_iam_role_policy.opensre_readonly,
  ]
}
```

- [ ] **Step 2: Append to `infra/outputs.tf`**

Add at the end of the file:

```terraform
output "opensre_host_instance_id" {
  description = "Pass to `aws ssm send-command` and `aws ssm start-session`. Null when var.opensre_host_enabled = false."
  value       = var.opensre_host_enabled ? aws_instance.opensre[0].id : null
}
```

- [ ] **Step 3: Validate Terraform**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Plan to verify (without EC2)**

With `opensre_host_enabled = false` (default), the EC2 won't be created yet. Run:

```bash
cd infra && terraform plan -out=plan-host.tfplan
```

Expected diff (additive on top of Task 1):
- `aws_iam_role.opensre_host`
- `aws_iam_role_policy_attachment.opensre_ssm`
- `aws_iam_role_policy.opensre_readonly`
- `aws_iam_role_policy.opensre_secrets`
- `aws_iam_instance_profile.opensre_host`
- `aws_security_group.opensre_host`
- (AMI data source resolves; no resource)
- **No** `aws_instance.opensre` because count = 0.

- [ ] **Step 5: Commit**

```bash
git add infra/opensre_host.tf infra/outputs.tf
git commit -m "feat(infra): add OpenSRE host EC2 + IAM + SG (gated by opensre_host_enabled)"
rm -f infra/plan-host.tfplan
```

---

## Task 4: SSM CloudWatch log group

**Files:**
- Create: `infra/ssm_logs.tf`
- Modify: `infra/outputs.tf` (append `opensre_ssm_log_group`)

- [ ] **Step 1: Create `infra/ssm_logs.tf`**

```terraform
# CloudWatch log group for SSM RunCommand stdout/stderr from `opensre investigate`.
# Plan 3's Lambda shim and Plan 2's helper script both invoke send-command with
#   --cloud-watch-output-config CloudWatchLogGroupName=/aws/ssm/opensre-investigate
# so streams land here, one per command-id. 7-day retention per spec §4.
resource "aws_cloudwatch_log_group" "opensre_investigate" {
  name              = "/aws/ssm/opensre-investigate"
  retention_in_days = 7

  tags = { Name = "${var.project}-opensre-investigate" }
}
```

- [ ] **Step 2: Append to `infra/outputs.tf`**

Add at the end:

```terraform
output "opensre_ssm_log_group" {
  description = "CloudWatch Log Group for `opensre investigate` stdout/stderr."
  value       = aws_cloudwatch_log_group.opensre_investigate.name
}
```

- [ ] **Step 3: Validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Plan**

Run: `cd infra && terraform plan -out=plan-logs.tfplan`
Expected: cumulative diff now adds `aws_cloudwatch_log_group.opensre_investigate` plus the new output.

- [ ] **Step 5: Commit**

```bash
git add infra/ssm_logs.tf infra/outputs.tf
git commit -m "feat(infra): add /aws/ssm/opensre-investigate log group"
rm -f infra/plan-logs.tfplan
```

---

## Task 5: First terraform apply + populate secrets

This is the **first of two applies**. Goal: create the IAM/SG/secret/log-group resources, then populate the two Secrets Manager values manually. The EC2 is *not* created yet (`opensre_host_enabled = false` by default).

- [ ] **Step 1: Confirm tfvars contain Plan-2 inputs**

Open `infra/terraform.tfvars` and confirm (or add):

```text
opensre_telegram_chat_id = "-1001234567890"   # your group's chat ID from Prerequisites
opensre_host_enabled     = false              # creates secrets shells only on this apply
```

The chat ID is **required** (no default) and must match the group you'll add the bot to. If you don't have an `infra/terraform.tfvars` yet, copy from the example and edit:

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
# Then edit: db_password, ui_bucket_suffix, opensre_telegram_chat_id, etc.
```

- [ ] **Step 2: Apply**

```bash
cd infra && terraform apply
# Confirm prompt with: yes
```

Expected: ~9 resources to add (IAM role + 3 policies + instance profile + SG + 2 secrets + log group). No EC2 yet.

- [ ] **Step 3: Capture secret IDs**

```bash
cd infra
ANTHROPIC_SECRET=$(terraform output -raw anthropic_secret_id)
TELEGRAM_SECRET=$(terraform output -raw telegram_secret_id)
echo "$ANTHROPIC_SECRET"
echo "$TELEGRAM_SECRET"
```

Expected:
```
opensre/anthropic_api_key
opensre/telegram_bot_token
```

- [ ] **Step 4: Populate the Anthropic secret**

```bash
read -rs -p "Anthropic API key (sk-ant-...): " ANTHROPIC_KEY && echo
aws secretsmanager put-secret-value \
  --secret-id "$ANTHROPIC_SECRET" \
  --secret-string "$ANTHROPIC_KEY"
unset ANTHROPIC_KEY
```

Expected: JSON response containing `"VersionStages": ["AWSCURRENT"]`.

- [ ] **Step 5: Populate the Telegram bot token**

```bash
read -rs -p "Telegram bot token (123456789:ABC...): " TELEGRAM_TOKEN && echo
aws secretsmanager put-secret-value \
  --secret-id "$TELEGRAM_SECRET" \
  --secret-string "$TELEGRAM_TOKEN"
unset TELEGRAM_TOKEN
```

Expected: JSON response with `"VersionStages": ["AWSCURRENT"]`.

- [ ] **Step 6: Verify both secrets are populated (length only — never print values)**

```bash
aws secretsmanager get-secret-value --secret-id "$ANTHROPIC_SECRET" \
  --query 'SecretString' --output text | wc -c
aws secretsmanager get-secret-value --secret-id "$TELEGRAM_SECRET" \
  --query 'SecretString' --output text | wc -c
```

Expected: each prints a positive integer (typically 100+ for Anthropic keys, ~46+ for Telegram bot tokens). If either prints `0` or `5` (length of literal "None"), the secret didn't populate — re-run Step 4 or 5.

- [ ] **Step 7: Commit (only what's safe to commit)**

There's nothing to commit from this task — secrets are populated outside Terraform. No git changes.

---

## Task 6: Second terraform apply + verify host bootstrapped

Now we flip `opensre_host_enabled = true` and let user-data run.

- [ ] **Step 1: Set `opensre_host_enabled = true`**

```bash
sed -i.bak 's/opensre_host_enabled = false/opensre_host_enabled = true/' infra/terraform.tfvars
rm -f infra/terraform.tfvars.bak
grep opensre_host_enabled infra/terraform.tfvars
```

Expected: `opensre_host_enabled = true`.

- [ ] **Step 2: Apply (creates the EC2)**

```bash
cd infra && terraform apply
```

Expected: 1 resource to add (`aws_instance.opensre[0]`). Confirm with `yes`. Apply takes ~30 s for the EC2 itself; user-data then runs for ~3–5 min on the box.

- [ ] **Step 3: Capture the host instance ID**

```bash
cd infra
HOST=$(terraform output -raw opensre_host_instance_id)
REGION=$(terraform output -raw aws_region)
echo "Instance: $HOST  Region: $REGION"
```

- [ ] **Step 4: Wait for SSM to register the instance (up to 2 min)**

```bash
for i in $(seq 1 24); do
  STATUS=$(aws ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=$HOST" \
    --region "$REGION" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo Pending)
  echo "[$i] PingStatus: $STATUS"
  [ "$STATUS" = "Online" ] && break
  sleep 5
done
```

Expected: eventually prints `PingStatus: Online`. If it never does after 24 iterations, check that the instance is `running` (`aws ec2 describe-instances --instance-ids $HOST --region $REGION`) and that the IAM role has `AmazonSSMManagedInstanceCore` attached.

- [ ] **Step 5: Tail the bootstrap log via SSM (read-only)**

```bash
aws ssm start-session \
  --target "$HOST" \
  --region "$REGION" \
  --document-name AWS-StartNonInteractiveCommand \
  --parameters '{"command":["sudo tail -n 200 /var/log/opensre-bootstrap/bootstrap.log"]}'
```

Expected: lines ending with `OpenSRE host bootstrap complete`.

If the log shows `FATAL: opensre/anthropic_api_key is empty` (or `telegram_bot_token`), Task 5 didn't populate one of the secrets. Recover:

```bash
# Re-populate the missing secret (Task 5 Steps 4 or 5), then:
cd infra && terraform taint 'aws_instance.opensre[0]' && terraform apply
```

- [ ] **Step 6: Confirm the success marker**

```bash
aws ssm start-session \
  --target "$HOST" \
  --region "$REGION" \
  --document-name AWS-StartNonInteractiveCommand \
  --parameters '{"command":["sudo test -f /var/log/opensre-bootstrap/bootstrap.ok && echo BOOTSTRAP_OK || echo BOOTSTRAP_INCOMPLETE"]}'
```

Expected: `BOOTSTRAP_OK`.

- [ ] **Step 7: Commit the tfvars flip is intentionally NOT committed**

`infra/terraform.tfvars` is gitignored (per Plan 1's `.gitignore`). Nothing to commit from this task.

---

## Task 7: Smoke test — `opensre integrations verify`

This re-runs OpenSRE's own integration check via SSM RunCommand, with output going to `/aws/ssm/opensre-investigate`. It validates that the IAM read-only policy + Anthropic are reachable from the host *after* the initial bootstrap. Telegram is independent of OpenSRE's integration set — it was already smoke-tested by the bootstrap "hello" message in Task 6 (Step 5/Step 6 should have shown a message in your group). If the bootstrap message did not arrive, fix that first (re-check chat ID, bot membership, token) before continuing here.

- [ ] **Step 1: Send the verify command**

```bash
cd infra
HOST=$(terraform output -raw opensre_host_instance_id)
REGION=$(terraform output -raw aws_region)
LOG_GROUP=$(terraform output -raw opensre_ssm_log_group)

CMD_ID=$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$HOST" \
  --document-name AWS-RunShellScript \
  --parameters '{"commands":["set -a; source /etc/opensre/.env; set +a","/usr/local/bin/opensre integrations verify"]}' \
  --cloud-watch-output-config "CloudWatchLogGroupName=$LOG_GROUP,CloudWatchOutputEnabled=true" \
  --timeout-seconds 120 \
  --comment "plan2-task7-integrations-verify" \
  --query 'Command.CommandId' --output text)
echo "CommandId: $CMD_ID"
```

Expected: `CommandId: <uuid>` printed.

- [ ] **Step 2: Poll until the command completes**

```bash
DEADLINE=$(($(date +%s) + 180))
while true; do
  STATUS=$(aws ssm get-command-invocation \
    --region "$REGION" --command-id "$CMD_ID" --instance-id "$HOST" \
    --query 'Status' --output text 2>/dev/null || echo Pending)
  echo "Status: $STATUS"
  case "$STATUS" in
    Success|Failed|TimedOut|Cancelled) break ;;
  esac
  [ $(date +%s) -ge $DEADLINE ] && { echo "Local poll timed out" >&2; break; }
  sleep 3
done
```

Expected: terminates with `Status: Success`.

- [ ] **Step 3: Inspect output**

```bash
aws ssm get-command-invocation \
  --region "$REGION" --command-id "$CMD_ID" --instance-id "$HOST" \
  --query 'StandardOutputContent' --output text | tail -n 50
```

Expected: OpenSRE prints each integration as connected/verified (exact format depends on current OpenSRE CLI; should be a green/OK line per integration). Status code 0.

If status is `Failed`, inspect `StandardErrorContent` similarly:

```bash
aws ssm get-command-invocation \
  --region "$REGION" --command-id "$CMD_ID" --instance-id "$HOST" \
  --query 'StandardErrorContent' --output text
```

Common failure modes: expired Anthropic key, IAM read-only missing a permission. (Telegram failures appear in Task 6 / Task 8, not here.) Address before continuing.

- [ ] **Step 4: Nothing to commit** — this is verification only.

---

## Task 8: Helper script + smoke test — `opensre investigate` with synthetic alert

This is the **headline check** for Plan 2: a synthetic CloudWatch-shaped alert is delivered to the host; SSM RunCommand sources `/etc/opensre/.env` and runs `opensre investigate -i /tmp/alert-<id>.json`; OpenSRE's built-in Telegram messaging integration posts the RCA to the configured group, where the OpenClaw bot ingests it.

**Files:**
- Create: `scripts/test_opensre_alert.sh`

- [ ] **Step 1: Create `scripts/test_opensre_alert.sh`**

```bash
#!/usr/bin/env bash
# Send a synthetic alert to the OpenSRE host via SSM RunCommand and poll for completion.
# SSM stdout streams to /aws/ssm/opensre-investigate (includes the curl response from
# the Telegram Bot API). The RCA itself lands in the configured Telegram group.
#
# Usage:
#   ./scripts/test_opensre_alert.sh                 # uses built-in CPU-saturation fixture
#   ./scripts/test_opensre_alert.sh path/alert.json # custom alert payload

set -euo pipefail

cd "$(dirname "$0")/.."

INSTANCE_ID=$(cd infra && terraform output -raw opensre_host_instance_id)
REGION=$(cd infra && terraform output -raw aws_region)
LOG_GROUP=$(cd infra && terraform output -raw opensre_ssm_log_group)

ALERT_FILE="${1:-}"
CLEANUP_FILE=""
if [ -z "$ALERT_FILE" ]; then
  ALERT_FILE=$(mktemp /tmp/synthetic-alert.XXXXXX.json)
  CLEANUP_FILE="$ALERT_FILE"
  cat > "$ALERT_FILE" <<'JSON'
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
  "raw_sns_message": {}
}
JSON
fi

PAYLOAD_B64=$(base64 < "$ALERT_FILE" | tr -d '\n')
INVOCATION_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
PARAMS_FILE=$(mktemp /tmp/ssm-params.XXXXXX.json)
trap 'rm -f "$PARAMS_FILE" "$CLEANUP_FILE"' EXIT

cat > "$PARAMS_FILE" <<JSON
{
  "commands": [
    "echo $PAYLOAD_B64 | base64 -d > /tmp/alert-$INVOCATION_ID.json",
    "set -a; . /etc/opensre/.env; set +a",
    "/usr/local/bin/opensre investigate -i /tmp/alert-$INVOCATION_ID.json"
  ]
}
JSON

CMD_ID=$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters "file://$PARAMS_FILE" \
  --cloud-watch-output-config "CloudWatchLogGroupName=$LOG_GROUP,CloudWatchOutputEnabled=true" \
  --timeout-seconds 600 \
  --comment "test-opensre-alert-$INVOCATION_ID" \
  --query 'Command.CommandId' --output text)

echo "CommandId:    $CMD_ID"
echo "InvocationId: $INVOCATION_ID"
echo "Polling status (up to 11 min)..."

DEADLINE=$(($(date +%s) + 660))
STATUS="Pending"
while true; do
  STATUS=$(aws ssm get-command-invocation \
    --region "$REGION" --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
    --query 'Status' --output text 2>/dev/null || echo Pending)
  case "$STATUS" in
    Success|Failed|TimedOut|Cancelled) break ;;
  esac
  if [ $(date +%s) -ge $DEADLINE ]; then
    echo "Local poll timed out" >&2
    break
  fi
  printf '.'
  sleep 5
done
echo
echo "Final status: $STATUS"

echo
echo "Tail logs:"
echo "  aws logs tail $LOG_GROUP --since 15m --region $REGION"
echo

if [ "$STATUS" != "Success" ]; then
  echo "FAIL: command did not succeed. Inspect:"
  echo "  aws ssm get-command-invocation --region $REGION --command-id $CMD_ID --instance-id $INSTANCE_ID --query StandardErrorContent --output text"
  exit 1
fi

echo "OK. Check the configured Telegram group for the RCA message (typically <5s after Success)."
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/test_opensre_alert.sh
```

- [ ] **Step 3: Lint**

```bash
bash -n scripts/test_opensre_alert.sh
```

Expected: no output. If `shellcheck` is installed: `shellcheck scripts/test_opensre_alert.sh`.

- [ ] **Step 4: Run the synthetic CPU-saturation smoke test**

```bash
./scripts/test_opensre_alert.sh
```

Expected output:
```
CommandId:    <uuid>
InvocationId: <uuid>
Polling status (up to 11 min)...
....................
Final status: Success

Tail logs:
  aws logs tail /aws/ssm/opensre-investigate --since 15m --region us-east-1

OK. Check the configured Telegram group for the RCA message (typically <5s after Success).
```

- [ ] **Step 5: Tail the agent's reasoning trace + Bot API response**

```bash
REGION=$(cd infra && terraform output -raw aws_region)
aws logs tail /aws/ssm/opensre-investigate --since 15m --region "$REGION" --format short
```

Expected: OpenSRE's stdout containing the alert echo, the investigation steps it took (CW metric queries, log filters), and the RCA summary. The Telegram POST itself is performed inside `opensre investigate` (built-in messaging integration), so its response is not always echoed to stdout — confirm delivery by checking the group directly (Step 6).

If the SSM command finishes `Success` but no Telegram message arrives, common causes: bot was removed from the group between bootstrap (Task 6 Step 5 wrote a "hello" successfully) and now; token revoked; chat ID changed. Fix the integration (re-invite bot, rotate token, update `var.opensre_telegram_chat_id` and re-apply) and re-run Task 8 Step 4.

- [ ] **Step 6: Verify Telegram**

Open the Telegram group (the one matching `var.opensre_telegram_chat_id`). Expected within ~5 s of "Final status: Success":

A message from your OpenSRE bot containing at minimum:
- The alarm name (`sut-cpu-saturation`)
- A short evidence summary (CW metric values around the breach)
- A root-cause hypothesis
- A recommended next action

Exact formatting is whatever OpenSRE's built-in Telegram messaging integration produces (truncated at 4 096 chars for long reports — see https://opensre.com/docs/messaging/telegram.md). As long as the message exists with those four elements and the OpenClaw bot in the group has acknowledged or processed it (per OpenClaw's behaviour, out of scope here), Plan 2 is verified.

- [ ] **Step 7: Commit the helper script**

```bash
git add scripts/test_opensre_alert.sh
git commit -m "feat(scripts): add test_opensre_alert.sh smoke test"
```

---

## Task 9: Documentation — `opensre_host/README.md` + main README update

**Files:**
- Create: `opensre_host/README.md`
- Modify: `README.md` (append a "Plan 2 quick start" section between Plan 1 quick start and Teardown)

- [ ] **Step 1: Create `opensre_host/README.md`**

```markdown
# OpenSRE host

The long-lived agent EC2 (`t3.micro`, AL2023) that runs `opensre investigate`
when SSM RunCommand delivers an alert payload. Provisioned by `infra/opensre_host.tf`,
bootstrapped by `user_data.sh.tftpl`.

## Files

- `user_data.sh.tftpl` — Terraform-templated bootstrap. Installs the OpenSRE
  CLI via `curl -fsSL https://install.opensre.com | bash`, fetches the two
  named secrets (`opensre/anthropic_api_key`, `opensre/telegram_bot_token`),
  writes `/etc/opensre/.env` (and a sibling `/etc/profile.d/opensre.sh` so
  every interactive shell auto-sources the env), runs
  `opensre integrations verify`, and posts a "hello" smoke message to the
  Telegram group via direct curl. Logs to `/var/log/opensre-bootstrap/bootstrap.log`.
  On success, touches `/var/log/opensre-bootstrap/bootstrap.ok`.

## How RCA delivery works

`opensre investigate -i <alert.json>` posts the RCA to Telegram via OpenSRE's
**built-in Telegram messaging integration** — no wrapper script. The integration
reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_DEFAULT_CHAT_ID` from the environment
(set by `/etc/opensre/.env` and auto-sourced by `/etc/profile.d/opensre.sh`).
Long reports are truncated to Telegram's 4 096-char per-message limit per
https://opensre.com/docs/messaging/telegram.md.

When invoking from SSM RunCommand, prefix the command with `set -a; . /etc/opensre/.env; set +a`
so the Telegram env vars are present (SSM RunCommand starts a fresh non-login
shell that doesn't auto-source `/etc/profile.d/`). Both the Plan-2 helper
(`scripts/test_opensre_alert.sh`) and Plan 3's Lambda do this.

## Inspecting the host

The host has **no inbound SG rules**. Reach it via SSM only:

```bash
HOST=$(cd infra && terraform output -raw opensre_host_instance_id)
REGION=$(cd infra && terraform output -raw aws_region)

# Interactive shell:
aws ssm start-session --target "$HOST" --region "$REGION"

# Tail bootstrap log:
aws ssm start-session --target "$HOST" --region "$REGION" \
  --document-name AWS-StartNonInteractiveCommand \
  --parameters '{"command":["sudo tail -n 200 /var/log/opensre-bootstrap/bootstrap.log"]}'

# Confirm /etc/opensre/.env exists (does not print contents):
aws ssm start-session --target "$HOST" --region "$REGION" \
  --document-name AWS-StartNonInteractiveCommand \
  --parameters '{"command":["sudo ls -l /etc/opensre/.env"]}'
```

## Re-running the bootstrap

If user-data failed (e.g. secrets were empty on first boot), recreate the instance
to retrigger user-data:

```bash
cd infra
terraform taint 'aws_instance.opensre[0]'
terraform apply
```

This destroys and recreates the EC2; the new instance runs user-data fresh.

## Updating `/etc/opensre/.env` after rotating a secret

If you `aws secretsmanager put-secret-value` to a new value, the running host
still has the old value cached in `/etc/opensre/.env`. Re-run the bootstrap-without-install
fragment manually via SSM:

```bash
HOST=$(cd infra && terraform output -raw opensre_host_instance_id)
REGION=$(cd infra && terraform output -raw aws_region)
aws ssm send-command --region "$REGION" --instance-ids "$HOST" \
  --document-name AWS-RunShellScript \
  --parameters '{"commands":[
    "AK=$(aws secretsmanager get-secret-value --secret-id opensre/anthropic_api_key --query SecretString --output text)",
    "TT=$(aws secretsmanager get-secret-value --secret-id opensre/telegram_bot_token --query SecretString --output text)",
    "TC=$(grep ^TELEGRAM_DEFAULT_CHAT_ID= /etc/opensre/.env | cut -d= -f2-)",
    "sudo install -d -m 0700 /etc/opensre",
    "sudo bash -c \"cat > /etc/opensre/.env <<E\nANTHROPIC_API_KEY=$AK\nTELEGRAM_BOT_TOKEN=$TT\nTELEGRAM_DEFAULT_CHAT_ID=$TC\nLLM_PROVIDER=anthropic\nLLM_MODEL=claude-sonnet-4-6\nE\"",
    "sudo chmod 600 /etc/opensre/.env"
  ]}'
```

Or simpler — and recommended for chat-ID changes too, since `var.opensre_telegram_chat_id` is baked into user-data: `cd infra && terraform taint 'aws_instance.opensre[0]' && terraform apply`.

## If `opensre investigate` complains "telegram not configured"

The plan assumes env-vars-only configuration is sufficient (per the integration
docs). If your OpenSRE version requires `opensre onboard` to register the
Telegram integration into a config file, run it interactively via SSM Session
Manager:

```bash
HOST=$(cd infra && terraform output -raw opensre_host_instance_id)
REGION=$(cd infra && terraform output -raw aws_region)
aws ssm start-session --target "$HOST" --region "$REGION"
# Once in the session:
sudo -i
set -a; . /etc/opensre/.env; set +a
opensre onboard
# Follow the prompts. Most fields are pre-populated from env vars.
exit
```

Then re-run `./scripts/test_opensre_alert.sh` to confirm the chain.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `bootstrap.log` ends with `FATAL: ...secret is empty` | Secret value never populated, or populated *after* user-data ran | Populate via `aws secretsmanager put-secret-value`, then `terraform taint 'aws_instance.opensre[0]' && terraform apply` |
| Bootstrap "hello" Telegram message never arrives | Bot not added to the group; chat ID wrong; token revoked | Re-invite the bot to the group; verify chat ID with `getUpdates`; rotate token if revoked; re-populate secret; `terraform taint 'aws_instance.opensre[0]' && terraform apply` |
| Bootstrap curl returns `{"ok":false,"error_code":403}` (forbidden) | Bot kicked from group / privacy/admin limits | Re-add the bot, ensure it has permission to post in the group |
| Bootstrap curl returns `{"ok":false,"error_code":400,"description":"chat not found"}` | Wrong `TELEGRAM_DEFAULT_CHAT_ID` (often missing the leading `-` for groups) | Update `var.opensre_telegram_chat_id` in tfvars and `terraform apply` (the EC2 will replace because user-data changed) |
| `opensre investigate` runs Success but no Telegram message | OpenSRE version requires `onboard` to register the integration even when env vars are set | SSM-Session in and run `opensre onboard` interactively (see "If `opensre investigate` complains" above) |
| SSM RunCommand returns `InvalidInstanceId` | Host not yet SSM-Online | Wait 1–2 min after `terraform apply`; check `aws ssm describe-instance-information` |
| `opensre investigate` takes >5 min | Long agent loop / Anthropic latency | Acceptable; spec p95 budget is ~3 min, p99 closer to 4–5 min. Hard-killed at 600 s by SSM timeout. |
```

- [ ] **Step 2: Append to `README.md`**

Open the existing `README.md`. Find the line that begins `## Teardown` and *insert the following block immediately above it* (the outer 4-backtick fence below is for display only — the actual content to paste is everything between the outer fences):

````markdown
## Plan 2 quick start (OpenSRE host)

Builds on Plan 1. Stands up the agent EC2 that runs `opensre investigate` and posts RCAs to a Telegram group (where the downstream OpenClaw bot picks them up).

```bash
# 0. Prereqs (in addition to Plan 1):
#    - Anthropic API key
#    - Telegram bot from @BotFather (capture token)
#    - Telegram group with: OpenSRE bot + OpenClaw bot (capture chat ID like -1001234567890)
#    - session-manager-plugin, uuidgen
#    Set opensre_telegram_chat_id in infra/terraform.tfvars before applying.

# 1. First apply — secrets shells only (opensre_host_enabled defaults to false).
cd infra && terraform apply

# 2. Populate the two Secrets Manager values.
ANTHROPIC_SECRET=$(terraform output -raw anthropic_secret_id)
TELEGRAM_SECRET=$(terraform output -raw telegram_secret_id)
read -rs -p "Anthropic API key: " AK && echo
aws secretsmanager put-secret-value --secret-id "$ANTHROPIC_SECRET" --secret-string "$AK" && unset AK
read -rs -p "Telegram bot token: " TT && echo
aws secretsmanager put-secret-value --secret-id "$TELEGRAM_SECRET" --secret-string "$TT" && unset TT

# 3. Flip the toggle and re-apply — creates the EC2 + runs user-data + posts a Telegram "hello".
sed -i.bak 's/opensre_host_enabled = false/opensre_host_enabled = true/' terraform.tfvars
rm -f terraform.tfvars.bak
terraform apply

# 4. Wait for SSM to register the instance, then verify bootstrap completed.
HOST=$(terraform output -raw opensre_host_instance_id)
REGION=$(terraform output -raw aws_region)
for i in $(seq 1 24); do
  S=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$HOST" \
        --region "$REGION" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo Pending)
  echo "[$i] PingStatus: $S"; [ "$S" = "Online" ] && break; sleep 5
done
# Check Telegram for the "[OpenSRE bootstrap] host i-... online ..." message.

# 5. End-to-end smoke test: synthetic CPU alert → real RCA in the Telegram group (consumed by OpenClaw).
cd .. && ./scripts/test_opensre_alert.sh
```

If the smoke test produces an RCA in the Telegram group (and OpenClaw acknowledges it downstream), Plan 2 is complete.
````

- [ ] **Step 3: Verify the README still renders cleanly**

```bash
# Quickest sanity check — the markdown should still have matching code fences.
grep -c '^```' README.md
```

Expected: an even number (every fence is paired). If odd, fix the imbalance.

- [ ] **Step 4: Commit**

```bash
git add opensre_host/README.md README.md
git commit -m "docs(plan-2): add OpenSRE host README and quick-start"
```

---

## Final validation checklist

Run in order; every item must pass before declaring Plan 2 complete.

- [ ] `cd infra && terraform plan` shows **No changes** (state matches code).
- [ ] `cd infra && terraform output opensre_host_instance_id` prints a non-null `i-…`.
- [ ] `aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$(cd infra && terraform output -raw opensre_host_instance_id)" --region $(cd infra && terraform output -raw aws_region) --query 'InstanceInformationList[0].PingStatus' --output text` prints `Online`.
- [ ] Bootstrap success marker exists: `aws ssm start-session --target … --document-name AWS-StartNonInteractiveCommand --parameters '{"command":["sudo test -f /var/log/opensre-bootstrap/bootstrap.ok && echo OK"]}'` prints `OK`.
- [ ] Task 7's `opensre integrations verify` returned `Status: Success`.
- [ ] Task 8's `./scripts/test_opensre_alert.sh` returned `Final status: Success` and an RCA appeared in the configured Telegram group containing alarm-name, evidence, hypothesis, recommended action — bracketed by `[OpenSRE RCA]` and `[OpenSRE END]` markers.
- [ ] The bootstrap "hello" message (from Task 6 user-data) is visible in the Telegram group.
- [ ] CloudWatch Logs Insights query against `/aws/ssm/opensre-investigate` over the last 30 min shows at least one `{"ok":true,...}` curl response from `api.telegram.org`.
- [ ] CloudWatch Logs Insights query against `/aws/ssm/opensre-investigate` over the last 30 min returns at least one log stream with the agent's stdout.

---

## Teardown notes (specific to Plan 2)

To avoid Free Tier overage between demos:

```bash
cd infra
sed -i.bak 's/opensre_host_enabled = true/opensre_host_enabled = false/' terraform.tfvars
rm -f terraform.tfvars.bak
terraform apply
```

This destroys the OpenSRE EC2 (saves ~750 h/mo) but **keeps** the secrets, IAM role, SG, and log group so Plan 3 still has things to reference. Re-flip to `true` to bring the host back; user-data re-runs and reads the still-populated secrets.

To fully tear down: `terraform destroy` (also wipes Plan 1).

---

## What this plan does NOT do (deferred to Plans 3 & 4)

- ❌ CloudWatch alarms (`sut-cpu-saturation`, `sut-db-connection-errors`).
- ❌ SNS topic + Lambda shim that auto-routes alarms to the host.
- ❌ FIS experiment templates that produce real degradation.
- ❌ End-to-end demo (`aws fis start-experiment`-driven).

Without those, Plan 2 is verified only by the synthetic-alert smoke test in Task 8. That's enough to prove the agent layer works in isolation.

---

*End of Plan 2.*
