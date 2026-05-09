"""SNS CloudWatch-alarm event -> ssm:SendCommand against the OpenSRE host.

Inputs (env vars, set by Terraform):
  OPENSRE_HOST_INSTANCE_ID  EC2 instance ID running the OpenSRE CLI.
  OPENSRE_SSM_LOG_GROUP     CloudWatch Logs group for SSM RunCommand stdout/stderr.
  SSM_TIMEOUT_SECONDS       SSM SendCommand TimeoutSeconds (default 600).

The invocation chain:
  SNS -> Lambda -> ssm:SendCommand -> AWS-RunShellScript ->
   . /etc/opensre/.env -> opensre investigate ->
   Telegram (built-in integration; reads TELEGRAM_BOT_TOKEN +
   TELEGRAM_DEFAULT_CHAT_ID from the sourced env).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid

import boto3

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

INSTANCE_ID = os.environ["OPENSRE_HOST_INSTANCE_ID"]
SSM_LOG_GROUP = os.environ["OPENSRE_SSM_LOG_GROUP"]
SSM_TIMEOUT_SECONDS = int(os.environ.get("SSM_TIMEOUT_SECONDS", "600"))

ssm = boto3.client("ssm")


def _build_resource(trigger: dict) -> dict:
    namespace = trigger.get("Namespace", "")
    if namespace == "AWS/ECS":
        dims = {d["name"]: d["value"] for d in trigger.get("Dimensions", [])}
        return {
            "type": "ecs-service",
            "cluster": dims.get("ClusterName", "unknown"),
            "service": dims.get("ServiceName", "unknown"),
        }
    if namespace.startswith("OpenSRE/SUT"):
        return {
            "type": "rds-instance",
            "instance_identifier": "opensre-demo-db",
        }
    return {"type": "unknown", "namespace": namespace}


def _build_alert_payload(cw_alarm: dict, raw_sns_message: dict, invocation_id: str) -> dict:
    """Normalise a CloudWatch alarm message into the OpenSRE alert envelope (spec §5.3)."""
    trigger = cw_alarm.get("Trigger", {})
    return {
        "source": "aws-cloudwatch",
        "alert_name": cw_alarm.get("AlarmName", "unknown"),
        "state": cw_alarm.get("NewStateValue", "ALARM"),
        "state_change_time": cw_alarm.get("StateChangeTime"),
        "region": cw_alarm.get("Region") or os.environ.get("AWS_REGION", "us-east-1"),
        "resource": _build_resource(trigger),
        "metric": {
            "namespace": trigger.get("Namespace"),
            "name": trigger.get("MetricName"),
            "threshold": trigger.get("Threshold"),
            "value_at_breach": None,
            "period_seconds": trigger.get("Period", 60),
        },
        "invocation_id": invocation_id,
        "raw_sns_message": raw_sns_message,
    }


def handler(event: dict, _context) -> dict:
    LOGGER.info("Received event: %s", json.dumps(event)[:1000])

    record = event["Records"][0]
    sns_message_str = record["Sns"]["Message"]
    cw_alarm = json.loads(sns_message_str)

    invocation_id = str(uuid.uuid4()).lower()
    payload = _build_alert_payload(cw_alarm, cw_alarm, invocation_id)

    payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    alert_path = f"/tmp/alert-{invocation_id}.json"

    commands = [
        f"echo {payload_b64} | base64 -d > {alert_path}",
        "set -a; . /etc/opensre/.env; set +a",
        f"/usr/local/bin/opensre investigate -i {alert_path}",
    ]

    LOGGER.info(
        "ssm:SendCommand instance=%s alarm=%s invocation=%s",
        INSTANCE_ID, payload["alert_name"], invocation_id,
    )

    response = ssm.send_command(
        InstanceIds=[INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
        CloudWatchOutputConfig={
            "CloudWatchLogGroupName": SSM_LOG_GROUP,
            "CloudWatchOutputEnabled": True,
        },
        TimeoutSeconds=SSM_TIMEOUT_SECONDS,
        Comment=f"opensre-{payload['alert_name']}-{invocation_id}",
    )

    command_id = response["Command"]["CommandId"]
    LOGGER.info(
        "ssm:SendCommand sent commandId=%s alarm=%s invocation=%s",
        command_id, payload["alert_name"], invocation_id,
    )

    return {
        "commandId": command_id,
        "alarmName": payload["alert_name"],
        "invocationId": invocation_id,
    }
