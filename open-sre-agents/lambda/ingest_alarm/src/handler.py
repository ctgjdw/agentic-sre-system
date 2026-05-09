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


SUT_LOG_GROUP = os.environ.get("SUT_LOG_GROUP", "/ecs/opensre-demo-sut")


def _build_annotations(cw_alarm: dict) -> dict:
    """Build annotations that tell OpenSRE where to look for evidence."""
    trigger = cw_alarm.get("Trigger", {})
    namespace = trigger.get("Namespace", "")
    dims = {d["name"]: d["value"] for d in trigger.get("Dimensions", [])}
    region = os.environ.get("AWS_REGION", "us-east-1")

    annotations = {
        "cloudwatch_log_group": SUT_LOG_GROUP,
        "cloudwatch_region": region,
        "context_sources": "cloudwatch",
        "error": cw_alarm.get("NewStateReason", ""),
    }

    if namespace == "AWS/ECS":
        annotations.update({
            "summary": (
                f"ECS service {dims.get('ServiceName', 'unknown')} in cluster "
                f"{dims.get('ClusterName', 'unknown')} has CPU >= "
                f"{trigger.get('Threshold', 80)}% for {trigger.get('Period', 60)}s"
            ),
            "ecs_cluster": dims.get("ClusterName", ""),
            "ecs_service": dims.get("ServiceName", ""),
        })
    elif namespace.startswith("OpenSRE/SUT"):
        annotations.update({
            "summary": (
                f"DB connection errors detected: {trigger.get('MetricName', 'DBConnectionErrors')} "
                f">= {trigger.get('Threshold', 1)} in {trigger.get('Period', 60)}s"
            ),
            "rds_instance": "opensre-demo-db",
        })
    else:
        annotations["summary"] = cw_alarm.get("AlarmDescription", "CloudWatch alarm triggered")

    return annotations


def _build_alert_payload(cw_alarm: dict, invocation_id: str) -> dict:
    """Build a Grafana/AlertManager-format payload that OpenSRE can parse."""
    alarm_name = cw_alarm.get("AlarmName", "unknown")
    trigger = cw_alarm.get("Trigger", {})
    dims = {d["name"]: d["value"] for d in trigger.get("Dimensions", [])}
    pipeline_name = dims.get("ServiceName") or "opensre-demo-sut"
    annotations = _build_annotations(cw_alarm)

    alert = {
        "status": "firing",
        "labels": {
            "alertname": alarm_name,
            "severity": "critical",
            "pipeline_name": pipeline_name,
            "environment": "demo",
        },
        "annotations": {
            "summary": annotations.get("summary", ""),
            "description": (
                f"CloudWatch alarm {alarm_name} transitioned to "
                f"{cw_alarm.get('NewStateValue', 'ALARM')}: "
                f"{cw_alarm.get('NewStateReason', '')}"
            ),
            "runbook_url": "",
        },
        "startsAt": cw_alarm.get("StateChangeTime", ""),
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": cw_alarm.get("AlarmArn", ""),
        "fingerprint": invocation_id,
    }

    return {
        "alert_name": alarm_name,
        "pipeline_name": pipeline_name,
        "severity": "critical",
        "alerts": [alert],
        "version": "4",
        "externalURL": "",
        "truncatedAlerts": 0,
        "groupLabels": {"alertname": alarm_name},
        "commonLabels": {
            "alertname": alarm_name,
            "severity": "critical",
            "pipeline_name": pipeline_name,
        },
        "commonAnnotations": annotations,
        "groupKey": f'{{}}:{{alertname="{alarm_name}"}}',
        "title": f"[FIRING:1] {alarm_name} critical - {pipeline_name}",
        "state": "alerting",
        "message": (
            f"**Firing**\n\n{annotations.get('summary', '')}\n"
            f"Alarm: {alarm_name}\nReason: {cw_alarm.get('NewStateReason', '')}"
        ),
        "alert_id": invocation_id,
    }


def handler(event: dict, _context) -> dict:
    LOGGER.info("Received event: %s", json.dumps(event)[:1000])

    record = event["Records"][0]
    sns_message_str = record["Sns"]["Message"]
    cw_alarm = json.loads(sns_message_str)

    invocation_id = str(uuid.uuid4()).lower()
    payload = _build_alert_payload(cw_alarm, invocation_id)

    payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    alert_path = f"/tmp/alert-{invocation_id}.json"

    # OpenSRE's AWS integration requires explicit AWS_ACCESS_KEY_ID /
    # AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN env vars — it doesn't
    # auto-discover the EC2 instance role. Fetch temporary creds from
    # IMDSv2 at invocation time so they're always fresh.
    fetch_aws_creds = (
        'IMDS_TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token'
        ' -H "X-aws-ec2-metadata-token-ttl-seconds: 60");'
        " ROLE=$(curl -fsS -H \"X-aws-ec2-metadata-token: $IMDS_TOKEN\""
        " http://169.254.169.254/latest/meta-data/iam/security-credentials/);"
        " CREDS=$(curl -fsS -H \"X-aws-ec2-metadata-token: $IMDS_TOKEN\""
        " http://169.254.169.254/latest/meta-data/iam/security-credentials/$ROLE);"
        " export AWS_ACCESS_KEY_ID=$(echo $CREDS | jq -r .AccessKeyId);"
        " export AWS_SECRET_ACCESS_KEY=$(echo $CREDS | jq -r .SecretAccessKey);"
        " export AWS_SESSION_TOKEN=$(echo $CREDS | jq -r .Token);"
        " export AWS_DEFAULT_REGION=${AWS_REGION:-us-east-1}"
    )

    commands = [
        f"echo {payload_b64} | base64 -d > {alert_path}",
        "set -a; . /etc/opensre/.env; set +a",
        fetch_aws_creds,
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
