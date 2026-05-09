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
