#!/usr/bin/env bash
# OpenSRE MVP — one-shot teardown script.
#
# Implements docs/superpowers/plans/build-and-teardown-plan.md "Teardown":
#   1. Stop any in-flight FIS experiments
#   2. terraform destroy
#   3. Verify cleanup (lists remaining tagged resources)
#   4. (Optional) Local cleanup of .terraform / state / tfvars / build/
#
# Compatibility: Linux, macOS, Windows Git Bash. No GNU-only flags.
#
# Usage:
#   ./scripts/teardown.sh                  # interactive confirmation
#   ./scripts/teardown.sh --yes            # skip confirmation prompt
#   ./scripts/teardown.sh --clean-local    # also delete local terraform state + tfvars
#   ./scripts/teardown.sh --yes --clean-local
#   ./scripts/teardown.sh --help

set -euo pipefail

#-----------------------------------------------------------------------------#
# Setup                                                                        #
#-----------------------------------------------------------------------------#

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
INFRA_DIR="$REPO_ROOT/infra"

log()  { printf '\033[1;34m[teardown]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m     %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[err]\033[0m      %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

#-----------------------------------------------------------------------------#
# Argument parsing                                                             #
#-----------------------------------------------------------------------------#

ASSUME_YES=0
CLEAN_LOCAL=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y)       ASSUME_YES=1 ;;
    --clean-local)  CLEAN_LOCAL=1 ;;
    -h|--help)
      sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

cd "$REPO_ROOT"

#-----------------------------------------------------------------------------#
# Prerequisite checks                                                          #
#-----------------------------------------------------------------------------#

command -v aws       >/dev/null 2>&1 || die "missing aws CLI"
command -v terraform >/dev/null 2>&1 || die "missing terraform"

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  die "AWS credentials not configured. Set AWS_PROFILE or run 'aws configure'."
fi

if [ ! -d "$INFRA_DIR/.terraform" ]; then
  die "no terraform state in $INFRA_DIR (.terraform missing). Nothing to destroy.
       If you want to remove orphaned cloud resources, do it manually via the AWS console."
fi

# Resolve the region from terraform state (prefer this over tfvars; tfvars may
# have been edited since the last apply).
tf_out() { (cd "$INFRA_DIR" && terraform output -raw "$1" 2>/dev/null) || true; }
REGION=$(tf_out aws_region)

# Fallback to tfvars if state has no outputs (partially destroyed).
if [ -z "$REGION" ] && [ -f "$INFRA_DIR/terraform.tfvars" ]; then
  REGION=$(grep -E '^region\s*=' "$INFRA_DIR/terraform.tfvars" \
    | sed -E 's/[^"]*"([^"]+)".*/\1/' || true)
fi
REGION="${REGION:-us-east-1}"
log "Region: $REGION"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "AWS account: $ACCOUNT_ID"

# Best-effort: pull the project name from tfvars so we can scope verification.
PROJECT="opensre-demo"
if [ -f "$INFRA_DIR/terraform.tfvars" ]; then
  TF_PROJECT=$(grep -E '^project\s*=' "$INFRA_DIR/terraform.tfvars" \
    | sed -E 's/[^"]*"([^"]+)".*/\1/' || true)
  PROJECT="${TF_PROJECT:-opensre-demo}"
fi
log "Project tag: $PROJECT"

#-----------------------------------------------------------------------------#
# Confirmation                                                                 #
#-----------------------------------------------------------------------------#

if [ "$ASSUME_YES" -eq 0 ]; then
  cat <<EOF

You are about to destroy ALL OpenSRE demo resources in:
  AWS account : $ACCOUNT_ID
  Region      : $REGION
  Project tag : $PROJECT

This will delete:
  - VPC, subnets, IGW, route tables, security groups
  - SUT EC2 + Elastic IP
  - OpenSRE EC2 (if running)
  - RDS db.t3.micro instance (skip_final_snapshot = true)
  - S3 UI bucket and contents
  - ECR repository and images
  - CloudWatch alarms + log groups
  - Lambda function + SNS topic
  - Secrets Manager secrets (immediate deletion; recovery_window = 0)
  - FIS experiment templates + IAM service role
  - All IAM roles, policies, instance profiles created by Terraform

EOF
  printf 'Type the project tag to confirm (\"%s\"): ' "$PROJECT"
  read -r CONFIRM
  [ "$CONFIRM" = "$PROJECT" ] || die "confirmation mismatch — aborting."
fi

#-----------------------------------------------------------------------------#
# 1. Stop in-flight FIS experiments                                            #
#-----------------------------------------------------------------------------#

log "Step 1 — stopping any in-flight FIS experiments..."

# `state.status` for active experiments: pending | initiating | running.
RUNNING_IDS=$(aws fis list-experiments --region "$REGION" \
  --query 'experiments[?state.status==`running` || state.status==`pending` || state.status==`initiating`].id' \
  --output text 2>/dev/null || true)

if [ -n "$RUNNING_IDS" ]; then
  for EXP_ID in $RUNNING_IDS; do
    log "  stopping experiment $EXP_ID"
    aws fis stop-experiment --region "$REGION" --id "$EXP_ID" >/dev/null 2>&1 || \
      warn "  could not stop $EXP_ID (may have completed in the meantime)"
  done
  log "  waiting up to 60 s for experiments to terminate..."
  for i in $(seq 1 12); do
    REMAINING=$(aws fis list-experiments --region "$REGION" \
      --query 'experiments[?state.status==`running` || state.status==`pending` || state.status==`initiating`].id' \
      --output text 2>/dev/null || true)
    [ -z "$REMAINING" ] && { log "  all experiments terminal."; break; }
    printf '.'
    sleep 5
  done
  echo
else
  log "  no running experiments."
fi

#-----------------------------------------------------------------------------#
# 2. Terraform destroy                                                         #
#-----------------------------------------------------------------------------#

log "Step 2 — terraform destroy..."
(
  cd "$INFRA_DIR"
  terraform destroy -input=false -auto-approve
)

#-----------------------------------------------------------------------------#
# 3. Verify cleanup                                                            #
#-----------------------------------------------------------------------------#

log "Step 3 — verifying cleanup..."

ORPHANS=0
check_empty() {
  local description="$1"
  local result="$2"
  if [ -n "$result" ]; then
    warn "  ORPHAN: $description -> $result"
    ORPHANS=1
  else
    log "  OK: $description gone"
  fi
}

check_empty "EC2 instances tagged Project=$PROJECT" \
  "$(aws ec2 describe-instances --region "$REGION" \
       --filters "Name=tag:Project,Values=$PROJECT" \
                 "Name=instance-state-name,Values=pending,running,stopping,stopped" \
       --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null || true)"

check_empty "RDS db.t3.micro $PROJECT-db" \
  "$(aws rds describe-db-instances --region "$REGION" \
       --query "DBInstances[?DBInstanceIdentifier=='$PROJECT-db'].DBInstanceIdentifier" \
       --output text 2>/dev/null || true)"

check_empty "S3 UI buckets ($PROJECT-ui-*)" \
  "$(aws s3api list-buckets \
       --query "Buckets[?starts_with(Name, '$PROJECT-ui-')].Name" \
       --output text 2>/dev/null || true)"

check_empty "ECR repository $PROJECT-sut" \
  "$(aws ecr describe-repositories --region "$REGION" \
       --query "repositories[?repositoryName=='$PROJECT-sut'].repositoryName" \
       --output text 2>/dev/null || true)"

check_empty "Secrets Manager secrets opensre/*" \
  "$(aws secretsmanager list-secrets --region "$REGION" \
       --query "SecretList[?starts_with(Name, 'opensre/')].Name" \
       --output text 2>/dev/null || true)"

check_empty "FIS experiment templates ($PROJECT-*)" \
  "$(aws fis list-experiment-templates --region "$REGION" \
       --query "experimentTemplates[?tags.Name && starts_with(tags.Name, '$PROJECT')].id" \
       --output text 2>/dev/null || true)"

check_empty "Lambda functions $PROJECT-*" \
  "$(aws lambda list-functions --region "$REGION" \
       --query "Functions[?starts_with(FunctionName, '$PROJECT-')].FunctionName" \
       --output text 2>/dev/null || true)"

check_empty "SNS topics $PROJECT-*" \
  "$(aws sns list-topics --region "$REGION" \
       --query "Topics[?contains(TopicArn, ':$PROJECT-')].TopicArn" \
       --output text 2>/dev/null || true)"

check_empty "CloudWatch alarms (sut-*)" \
  "$(aws cloudwatch describe-alarms --region "$REGION" \
       --alarm-name-prefix sut- \
       --query 'MetricAlarms[].AlarmName' --output text 2>/dev/null || true)"

check_empty "VPCs tagged Project=$PROJECT" \
  "$(aws ec2 describe-vpcs --region "$REGION" \
       --filters "Name=tag:Project,Values=$PROJECT" \
       --query 'Vpcs[].VpcId' --output text 2>/dev/null || true)"

check_empty "Elastic IPs tagged Project=$PROJECT" \
  "$(aws ec2 describe-addresses --region "$REGION" \
       --filters "Name=tag:Project,Values=$PROJECT" \
       --query 'Addresses[].AllocationId' --output text 2>/dev/null || true)"

# Log groups don't always carry tags, so query by name prefix.
check_empty "CloudWatch log groups (/ecs/$PROJECT-*, /aws/lambda/$PROJECT-*, /aws/ssm/opensre-*)" \
  "$(
    {
      aws logs describe-log-groups --region "$REGION" \
        --log-group-name-prefix "/ecs/$PROJECT-" \
        --query 'logGroups[].logGroupName' --output text 2>/dev/null || true
      aws logs describe-log-groups --region "$REGION" \
        --log-group-name-prefix "/aws/lambda/$PROJECT-" \
        --query 'logGroups[].logGroupName' --output text 2>/dev/null || true
      aws logs describe-log-groups --region "$REGION" \
        --log-group-name-prefix "/aws/ssm/opensre" \
        --query 'logGroups[].logGroupName' --output text 2>/dev/null || true
    } | tr '\n' ' ' | sed 's/[[:space:]]*$//'
  )"

if [ "$ORPHANS" -eq 1 ]; then
  warn "Some resources remain. See docs/superpowers/plans/build-and-teardown-plan.md"
  warn "-> 'Destroy left orphans' for the cleanup commands."
fi

#-----------------------------------------------------------------------------#
# 4. Optional local cleanup                                                    #
#-----------------------------------------------------------------------------#

if [ "$CLEAN_LOCAL" -eq 1 ]; then
  log "Step 4 — local cleanup (--clean-local)..."
  rm -rf "$INFRA_DIR/.terraform" \
         "$INFRA_DIR/.terraform.lock.hcl" \
         "$INFRA_DIR/terraform.tfstate" \
         "$INFRA_DIR/terraform.tfstate.backup" \
         "$INFRA_DIR/terraform.tfvars" \
         "$INFRA_DIR/build" \
         "$INFRA_DIR"/*.tfplan
  log "  removed local terraform state and tfvars"
else
  log "Step 4 — skipping local cleanup (re-run with --clean-local to also remove .terraform / tfstate / tfvars)."
fi

#-----------------------------------------------------------------------------#
# Summary                                                                      #
#-----------------------------------------------------------------------------#

echo
if [ "$ORPHANS" -eq 0 ]; then
  log "Teardown complete. No orphans detected in $REGION."
else
  warn "Teardown finished with $ORPHANS orphan check(s) failing — investigate above."
fi
