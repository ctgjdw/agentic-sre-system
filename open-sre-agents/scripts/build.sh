#!/usr/bin/env bash
# OpenSRE MVP — one-shot build script.
#
# Orchestrates Phases B–F of docs/superpowers/plans/build-and-teardown-plan.md:
#   1. Verify prerequisites and tfvars
#   2. Cold terraform apply (sut_desired_count=0, opensre_host_enabled=false)
#   3. Build & push backend image to ECR
#   4. Seed RDS via SSM port-forward
#   5. Populate Secrets Manager (Anthropic + Telegram) — prompts if empty
#   6. Hot terraform apply (sut_desired_count=1, opensre_host_enabled=true)
#   7. Wait for SUT health + OpenSRE host SSM Online
#   8. Deploy UI to S3
#
# Idempotent: re-running after a partial success skips completed steps.
#
# Compatibility: Linux, macOS, Windows Git Bash. No GNU-only flags, no uuidgen,
# no /dev/tcp limitations. Works with bash 3.2+ (macOS default).
#
# Usage:
#   ./scripts/build.sh                   # interactive (prompts for missing secrets)
#   ./scripts/build.sh --skip-verify     # skip the post-build verification gates
#   ./scripts/build.sh --help

set -euo pipefail

#-----------------------------------------------------------------------------#
# Constants                                                                    #
#-----------------------------------------------------------------------------#

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
INFRA_DIR="$REPO_ROOT/infra"
TFVARS="$INFRA_DIR/terraform.tfvars"
TFVARS_EXAMPLE="$INFRA_DIR/terraform.tfvars.example"

PORT_FORWARD_LOCAL_PORT=15432
SSM_TIMEOUT_SECONDS=120          # how long to wait for SSM to register the OpenSRE host
SUT_HEALTH_TIMEOUT_SECONDS=180   # how long to wait for /health to return 200

#-----------------------------------------------------------------------------#
# Logging                                                                      #
#-----------------------------------------------------------------------------#

log()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m  %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[err]\033[0m   %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

#-----------------------------------------------------------------------------#
# Argument parsing                                                             #
#-----------------------------------------------------------------------------#

SKIP_VERIFY=0
for arg in "$@"; do
  case "$arg" in
    --skip-verify) SKIP_VERIFY=1 ;;
    -h|--help)
      sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

cd "$REPO_ROOT"

#-----------------------------------------------------------------------------#
# 0. Prerequisite checks                                                       #
#-----------------------------------------------------------------------------#

log "Checking prerequisites..."

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required tool: $1 ($2)"
}
require_cmd aws       "install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
require_cmd terraform "install Terraform 1.9+: https://developer.hashicorp.com/terraform/install"
require_cmd docker    "install Docker Desktop with buildx support"
require_cmd uv        "install uv: https://docs.astral.sh/uv/getting-started/installation/"
require_cmd node      "install Node.js 20+: https://nodejs.org/"
require_cmd npm       "ships with Node.js"
require_cmd jq        "install jq: https://stedolan.github.io/jq/download/"

# session-manager-plugin is invoked by aws-cli; check separately so the failure
# message is actionable.
if ! command -v session-manager-plugin >/dev/null 2>&1; then
  die "missing session-manager-plugin (required for SSM port-forward to seed RDS).
       https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html"
fi

# Pick a Python interpreter (Windows often has only 'python', not 'python3').
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  die "missing python (need python3.6+ to generate fallback values)"
fi

# Verify AWS credentials resolve.
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  die "AWS credentials not configured. Set AWS_PROFILE or run 'aws configure'."
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "AWS account: $ACCOUNT_ID"

#-----------------------------------------------------------------------------#
# 1. terraform.tfvars                                                          #
#-----------------------------------------------------------------------------#

if [ ! -f "$TFVARS" ]; then
  warn "$TFVARS not found — bootstrapping from terraform.tfvars.example"
  [ -f "$TFVARS_EXAMPLE" ] || die "$TFVARS_EXAMPLE missing; cannot bootstrap"
  cp "$TFVARS_EXAMPLE" "$TFVARS"

  # Generate strong random values for the two fields most likely to need rotation.
  RANDOM_DB_PW=$("$PYTHON" -c 'import secrets, string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24)))')
  RANDOM_UI_SUFFIX=$("$PYTHON" -c 'import secrets; print(secrets.token_hex(4))')

  # In-place replace the example placeholders. Avoid `sed -i` differences
  # between BSD/GNU/Git-Bash by writing to a tempfile and moving.
  TMP_FILE=$(mktemp "${TMPDIR:-/tmp}/tfvars.XXXXXX")
  awk -v pw="$RANDOM_DB_PW" -v suf="$RANDOM_UI_SUFFIX" '
    /^db_password/      { print "db_password       = \"" pw "\""; next }
    /^ui_bucket_suffix/ { print "ui_bucket_suffix  = \"" suf "\""; next }
    { print }
  ' "$TFVARS" > "$TMP_FILE"
  mv "$TMP_FILE" "$TFVARS"

  warn "Created $TFVARS with generated db_password + ui_bucket_suffix."
  warn "EDIT $TFVARS now to set:"
  warn "  - region (default us-east-1)"
  warn "  - sut_ingress_cidr (default 0.0.0.0/0; set <your-ip>/32 to restrict)"
  warn "  - opensre_telegram_chat_id (your Telegram group ID, e.g. -1001234567890)"
  warn "Then re-run this script."
  exit 1
fi

# Sanity-check the tfvars: refuse to apply with example placeholders still in place.
if grep -qE '^db_password\s*=\s*"REPLACE_ME' "$TFVARS"; then
  die "$TFVARS still contains the example db_password placeholder. Edit it first."
fi
if grep -qE '^opensre_telegram_chat_id\s*=\s*"-1001234567890"' "$TFVARS"; then
  die "$TFVARS still has the example opensre_telegram_chat_id. Set your real group chat ID."
fi
if grep -qE '^ui_bucket_suffix\s*=\s*"abc123def"' "$TFVARS"; then
  die "$TFVARS still has the example ui_bucket_suffix. Pick a unique value."
fi

# Extract a couple of values we'll need outside Terraform (DB password for seed).
DB_PW=$(grep -E '^db_password\s*=' "$TFVARS" | sed -E 's/[^"]*"([^"]+)".*/\1/')
[ -n "$DB_PW" ] || die "could not extract db_password from $TFVARS"

#-----------------------------------------------------------------------------#
# 2. Cold apply: VPC + RDS + ECR + S3 + Secrets shells (no SUT task, no host)  #
#-----------------------------------------------------------------------------#

log "Phase B — cold terraform apply (sut_desired_count=0, opensre_host_enabled=false)..."

(
  cd "$INFRA_DIR"
  if [ ! -d .terraform ]; then
    log "  terraform init"
    terraform init -input=false
  fi
  terraform apply -input=false -auto-approve \
    -var "sut_desired_count=0" \
    -var "opensre_host_enabled=false"
)

# Helper: read a terraform output as raw text.
tf_out() { (cd "$INFRA_DIR" && terraform output -raw "$1"); }

REGION=$(tf_out aws_region)
ECR_URL=$(tf_out ecr_repository_url)
SUT_INSTANCE_ID=$(tf_out sut_instance_id)
RDS_ADDRESS=$(tf_out rds_address)
ANTHROPIC_SECRET=$(tf_out anthropic_secret_id)
TELEGRAM_SECRET=$(tf_out telegram_secret_id)
log "  region=$REGION  ecr=$ECR_URL  sut_instance=$SUT_INSTANCE_ID"

# Wait for RDS to leave 'creating' state before we try to seed.
log "Waiting for RDS to be available..."
for i in $(seq 1 60); do
  STATUS=$(aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier opensre-demo-db \
    --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || echo unknown)
  case "$STATUS" in
    available) log "  RDS available."; break ;;
    *) printf '.'; sleep 10 ;;
  esac
  [ "$i" -eq 60 ] && die "RDS did not become available within 10 minutes (status=$STATUS)"
done

#-----------------------------------------------------------------------------#
# 3. Backend image build + push                                                #
#-----------------------------------------------------------------------------#

log "Phase C1 — building and pushing backend image..."

# Skip the docker push if :latest already exists in ECR with this content hash.
# (Cheap shortcut for re-runs; full check would compare digests.)
if aws ecr describe-images --region "$REGION" --repository-name opensre-demo-sut \
     --image-ids imageTag=latest >/dev/null 2>&1; then
  log "  ECR :latest already present — skipping login+push (re-run with --force-image to override)."
  PUSH_IMAGE=0
else
  PUSH_IMAGE=1
fi

# Allow operator override.
case " $* " in *" --force-image "*) PUSH_IMAGE=1 ;; esac

if [ "$PUSH_IMAGE" -eq 1 ]; then
  ECR_REGISTRY="${ECR_URL%/*}"
  log "  docker login to $ECR_REGISTRY"
  aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$ECR_REGISTRY"

  log "  docker buildx build --platform linux/amd64 -> $ECR_URL:latest"
  docker buildx build \
    --platform linux/amd64 \
    -t "$ECR_URL:latest" \
    --load \
    "$REPO_ROOT/backend"

  log "  docker push $ECR_URL:latest"
  docker push "$ECR_URL:latest"
fi

#-----------------------------------------------------------------------------#
# 4. Seed RDS via SSM port-forward                                             #
#-----------------------------------------------------------------------------#

log "Phase C2 — opening SSM port-forward $RDS_ADDRESS:5432 -> localhost:$PORT_FORWARD_LOCAL_PORT..."

# Run the session in background. Capture PID so we can clean up reliably.
SSM_PARAMS=$(printf '{"host":["%s"],"portNumber":["5432"],"localPortNumber":["%s"]}' \
  "$RDS_ADDRESS" "$PORT_FORWARD_LOCAL_PORT")

# Redirect stdin from /dev/null so the background session-manager-plugin
# doesn't compete with the parent shell for terminal input on Git Bash.
aws ssm start-session \
  --region "$REGION" \
  --target "$SUT_INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "$SSM_PARAMS" \
  </dev/null >/dev/null 2>&1 &
PORTFWD_PID=$!

# Make sure we kill the port-forward on any exit (success or failure).
cleanup_portfwd() {
  if kill -0 "$PORTFWD_PID" 2>/dev/null; then
    kill "$PORTFWD_PID" 2>/dev/null || true
    wait "$PORTFWD_PID" 2>/dev/null || true
  fi
}
trap cleanup_portfwd EXIT

# Wait up to 30 s for the local port to start accepting connections.
log "  waiting for local port $PORT_FORWARD_LOCAL_PORT to open..."
PORT_OPEN=0
for i in $(seq 1 30); do
  if "$PYTHON" -c "
import socket, sys
s = socket.socket()
s.settimeout(1)
try:
    s.connect(('127.0.0.1', $PORT_FORWARD_LOCAL_PORT))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    PORT_OPEN=1
    break
  fi
  sleep 1
done

[ "$PORT_OPEN" -eq 1 ] || die "port-forward never came up; check session-manager-plugin install"
log "  port-forward established."

log "Phase C3 — seeding RDS (10 000 rows; idempotent)..."
SEED_DATABASE_URL="postgresql://opensre:${DB_PW}@localhost:${PORT_FORWARD_LOCAL_PORT}/opensre_demo" \
  uv run "$REPO_ROOT/scripts/seed_posts.py"

cleanup_portfwd
trap - EXIT

#-----------------------------------------------------------------------------#
# 5. Populate Secrets Manager                                                  #
#-----------------------------------------------------------------------------#

log "Phase D — Secrets Manager..."

secret_is_empty() {
  local sid="$1"
  local val
  val=$(aws secretsmanager get-secret-value \
    --secret-id "$sid" --region "$REGION" \
    --query SecretString --output text 2>/dev/null || true)
  # AWS prints "None" when the value has never been set.
  [ -z "$val" ] || [ "$val" = "None" ]
}

prompt_secret() {
  local label="$1"
  local sid="$2"
  local value=""
  printf '  %s: ' "$label" >&2
  # Read silently from the controlling TTY (works in Git Bash + POSIX shells).
  if [ -t 0 ]; then
    stty -echo
    IFS= read -r value
    stty echo
    printf '\n' >&2
  else
    IFS= read -r value
  fi
  [ -n "$value" ] || die "$label cannot be empty"
  aws secretsmanager put-secret-value \
    --region "$REGION" \
    --secret-id "$sid" \
    --secret-string "$value" >/dev/null
  unset value
}

if secret_is_empty "$ANTHROPIC_SECRET"; then
  log "  $ANTHROPIC_SECRET is empty — prompting."
  prompt_secret "Anthropic API key (sk-ant-...)" "$ANTHROPIC_SECRET"
else
  log "  $ANTHROPIC_SECRET already populated — skipping."
fi

if secret_is_empty "$TELEGRAM_SECRET"; then
  log "  $TELEGRAM_SECRET is empty — prompting."
  prompt_secret "Telegram bot token (123456:ABC...)" "$TELEGRAM_SECRET"
else
  log "  $TELEGRAM_SECRET already populated — skipping."
fi

#-----------------------------------------------------------------------------#
# 6. Hot apply: SUT task + OpenSRE host                                        #
#-----------------------------------------------------------------------------#

log "Phase E — hot terraform apply (sut_desired_count=1, opensre_host_enabled=true)..."

(
  cd "$INFRA_DIR"
  terraform apply -input=false -auto-approve \
    -var "sut_desired_count=1" \
    -var "opensre_host_enabled=true"
)

# Persist the post-build (hot) state into tfvars so a subsequent manual
# `terraform apply` (without -var overrides) doesn't drift back to cold.
# Replaces only the value after "=" on the matching key line; preserves
# anything else on the line.
update_tfvar() {
  local key="$1"
  local value="$2"
  local tmp
  tmp=$(mktemp "${TMPDIR:-/tmp}/tfvars.XXXXXX")
  awk -v k="$key" -v v="$value" '
    BEGIN { kre = "^[[:space:]]*" k "[[:space:]]*=" }
    $0 ~ kre { idx = index($0, "="); print substr($0, 1, idx) " " v; next }
    { print }
  ' "$TFVARS" > "$tmp"
  mv "$tmp" "$TFVARS"
}
update_tfvar sut_desired_count 1
update_tfvar opensre_host_enabled true
log "  updated $TFVARS to the post-build (hot) state"

SUT_API=$(tf_out sut_api_url)
HOST_INSTANCE_ID=$(tf_out opensre_host_instance_id)
log "  sut_api=$SUT_API  opensre_host=$HOST_INSTANCE_ID"

# Wait for SUT health.
log "Waiting for SUT $SUT_API/health (max ${SUT_HEALTH_TIMEOUT_SECONDS}s)..."
DEADLINE=$(( $(date +%s) + SUT_HEALTH_TIMEOUT_SECONDS ))
SUT_OK=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  if curl -fsS --max-time 5 "$SUT_API/health" >/dev/null 2>&1; then
    SUT_OK=1; break
  fi
  printf '.'
  sleep 10
done
echo
[ "$SUT_OK" -eq 1 ] || warn "SUT /health didn't return 200 within timeout. Continuing — task may still be starting."

# Wait for OpenSRE host SSM Online.
log "Waiting for OpenSRE host SSM Online (max ${SSM_TIMEOUT_SECONDS}s)..."
DEADLINE=$(( $(date +%s) + SSM_TIMEOUT_SECONDS ))
SSM_OK=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  STATUS=$(aws ssm describe-instance-information \
    --region "$REGION" \
    --filters "Key=InstanceIds,Values=$HOST_INSTANCE_ID" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo Pending)
  if [ "$STATUS" = "Online" ]; then
    SSM_OK=1; break
  fi
  printf '.'
  sleep 5
done
echo
[ "$SSM_OK" -eq 1 ] || warn "OpenSRE host did not become SSM Online within timeout. Bootstrap may still be running — check Telegram for the [OpenSRE bootstrap] message."

#-----------------------------------------------------------------------------#
# 7. Deploy UI                                                                 #
#-----------------------------------------------------------------------------#

log "Phase F — deploying UI..."
"$REPO_ROOT/scripts/deploy_ui.sh"

UI_URL=$(tf_out ui_website_url)
log "  UI URL: $UI_URL"

#-----------------------------------------------------------------------------#
# 8. Summary + next steps                                                      #
#-----------------------------------------------------------------------------#

cat <<EOF

========================================================================
  Build complete.
========================================================================

  UI                : $UI_URL
  SUT API           : $SUT_API
  OpenSRE host      : $HOST_INSTANCE_ID  (region $REGION)
  RDS endpoint      : $RDS_ADDRESS
  Telegram chat     : $(grep -E '^opensre_telegram_chat_id' "$TFVARS" | sed -E 's/[^"]*"([^"]+)".*/\1/')

  A "[OpenSRE bootstrap] host $HOST_INSTANCE_ID online ..." message
  should already be in the Telegram group. If not, see
  docs/superpowers/plans/build-and-teardown-plan.md
  -> "Bootstrap fails (secret empty or host stuck in Pending)".

EOF

if [ "$SKIP_VERIFY" -eq 1 ]; then
  log "Skipping verification gates (--skip-verify)."
  log "Run smoke tests later:"
  log "  ./scripts/test_opensre_alert.sh   # Plan 2 layer"
  log "  ./scripts/start_chaos.sh cpu      # Plan 5 layer (full MVP)"
  exit 0
fi

cat <<EOF
Recommended verification gates (run when ready):

  G1 (synthetic alert -> Telegram):
    ./scripts/test_opensre_alert.sh

  G2 (manual alarm transition -> Telegram):
    ALARM_CPU=\$(cd infra && terraform output -raw alarm_cpu_name)
    aws cloudwatch set-alarm-state --region $REGION \\
      --alarm-name "\$ALARM_CPU" --state-value ALARM --state-reason "G2 smoke"

  G3 (FIS chaos -> Telegram, the MVP success criterion):
    ./scripts/start_chaos.sh cpu --follow
    ./scripts/start_chaos.sh rds

EOF
