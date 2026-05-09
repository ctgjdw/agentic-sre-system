#!/usr/bin/env bash
# Start a Plan-5 FIS experiment. Selects the template by name, prints the
# experiment ID, and (optionally) tail-follows the SSM log group so the
# operator can watch the alarm-to-Telegram chain.
#
# Usage:
#   ./scripts/start_chaos.sh cpu                # start cpu-load-burst, then return
#   ./scripts/start_chaos.sh rds                # start rds-reboot, then return
#   ./scripts/start_chaos.sh cpu --follow       # also tail /aws/ssm/opensre-investigate
#   ./scripts/start_chaos.sh rds --follow

set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
  echo "usage: $0 <cpu|rds> [--follow]" >&2
  exit 1
fi

SCENARIO="$1"
FOLLOW=0
if [ "${2:-}" = "--follow" ]; then FOLLOW=1; fi

REGION=$(cd infra && terraform output -raw aws_region)
SSM_LOG=$(cd infra && terraform output -raw opensre_ssm_log_group)

case "$SCENARIO" in
  cpu)
    TEMPLATE_ID=$(cd infra && terraform output -raw fis_cpu_load_burst_template_id)
    DESCRIPTION="cpu-load-burst (load_runner.py from OpenSRE host) targeting opensre-demo-sut"
    ;;
  rds)
    TEMPLATE_ID=$(cd infra && terraform output -raw fis_rds_reboot_template_id)
    DESCRIPTION="rds-reboot of opensre-demo-db"
    ;;
  *)
    echo "unknown scenario: $SCENARIO (expected cpu|rds)" >&2
    exit 1
    ;;
esac

if [ -z "$TEMPLATE_ID" ]; then
  echo "ERROR: terraform output fis_*_template_id is empty. Run 'cd infra && terraform apply' first." >&2
  exit 1
fi

echo "Starting FIS experiment: $DESCRIPTION"
echo "  region:      $REGION"
echo "  template-id: $TEMPLATE_ID"

EXPERIMENT_ID=$(aws fis start-experiment \
  --region "$REGION" \
  --experiment-template-id "$TEMPLATE_ID" \
  --query 'experiment.id' --output text)

echo "  experiment:  $EXPERIMENT_ID"
echo
echo "Watch experiment progress:"
echo "  aws fis get-experiment --region $REGION --id $EXPERIMENT_ID --query 'experiment.state' --output json"
echo
echo "Expected within ~3 minutes:"
echo "  - CW alarm transitions OK -> ALARM"
echo "  - Lambda log /aws/lambda/ingest_alarm shows ssm:SendCommand"
echo "  - SSM log $SSM_LOG shows opensre investigate stdout"
echo "  - RCA arrives in the configured Telegram group"
echo

if [ $FOLLOW -eq 1 ]; then
  echo "Tailing $SSM_LOG (Ctrl-C to stop)..."
  exec aws logs tail "$SSM_LOG" --since 1m --region "$REGION" --follow --format short
fi
