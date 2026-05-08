# OpenSRE MVP — Plan 3: Alert Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire CloudWatch alarms to the Plan-2 OpenSRE host via SNS + Lambda. After this plan, manually setting an alarm to ALARM (or any genuine breach) produces a real RCA in the configured Telegram group, *without* needing FIS — Plan 4 adds the chaos triggers.

**Architecture:** A CloudWatch Logs metric filter (`sut-db-connection-errors`) on the SUT log group emits a custom metric `OpenSRE/SUT/DBConnectionErrors`. Two CloudWatch Alarms — `sut-cpu-saturation` (CPU ≥ 80%) and `sut-db-connection-errors` (custom metric ≥ 1) — publish to SNS topic `opensre-alarms` on state change to ALARM. The topic's only subscriber is a Python 3.12 Lambda `ingest_alarm` (256 MB, 30 s timeout) that parses the SNS payload, normalises it into the OpenSRE alert envelope (spec §5.3), base64-encodes it, and calls `ssm:SendCommand` against the OpenSRE host with `CloudWatchOutputConfig` enabled. The SSM command sources Plan 2's `/etc/opensre/.env` (so `TELEGRAM_BOT_TOKEN` + `TELEGRAM_DEFAULT_CHAT_ID` are in scope) and runs `/usr/local/bin/opensre investigate -i /tmp/alert-<id>.json`. OpenSRE's built-in Telegram messaging integration posts the RCA directly — no wrapper script.

**Tech Stack:** Terraform 1.9+ with AWS provider 5.x · CloudWatch Alarms + Logs metric filters · SNS · AWS Lambda Python 3.12 (no vendored deps; runtime ships boto3) · SSM RunCommand · pytest with `unittest.mock`

---

## Prerequisites

- **Plan 1 + Plan 2 must be fully applied** with `opensre_host_enabled = true`. Confirm:

```bash
cd infra
terraform output opensre_host_instance_id   # prints i-...
terraform output opensre_ssm_log_group       # prints /aws/ssm/opensre-investigate
./../scripts/test_opensre_alert.sh           # produces RCA in Telegram (Plan-2 verification)
```

If `test_opensre_alert.sh` doesn't deliver a Telegram message, fix Plan 2 first — Plan 3 only adds the alarm-driven trigger; the OpenSRE-investigate-then-Telegram leg must already be working.

- **`uv`** locally (used by Plan 1 already; for Lambda tests).
- **`zip`** locally (`zip --version`); used implicitly by `archive_file`.
- **Python 3.12** locally for unit tests (matches Lambda runtime).

**Doc-verification:** confirm the latest `aws_lambda_function`, `aws_cloudwatch_metric_alarm`, and `aws_cloudwatch_log_metric_filter` resource shapes via `find-docs` (or `ctx7`) for the AWS Terraform provider — minor argument-name changes are common across major releases. The metric-filter `pattern` syntax is documented at https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntax.html.

---

## File Structure

Files this plan creates:

```
open-sre-agents/
├── infra/
│   ├── alarms.tf                          # NEW: SNS topic + metric filter + 2 CW alarms
│   └── lambda.tf                          # NEW: Lambda function + IAM + log group + SNS subscription
└── lambda/
    └── ingest_alarm/
        ├── pyproject.toml                 # NEW: uv project for tests; runtime needs nothing extra
        ├── src/
        │   └── handler.py                 # NEW: SNS → ssm:SendCommand
        └── tests/
            ├── __init__.py                # NEW
            ├── conftest.py                # NEW: env-var + boto3 fixtures
            └── test_handler.py            # NEW
```

Files this plan modifies:

```
open-sre-agents/
├── infra/outputs.tf                        # add SNS topic ARN, Lambda function name, alarm names
└── README.md                               # add Plan 3 quick-start
```

**Why `lambda/ingest_alarm/src/handler.py`:** the `src/` subdir cleanly delimits what ends up in the Lambda zip — `archive_file source_dir = lambda/ingest_alarm/src` packages only `handler.py` (no tests, no `pyproject.toml`, no `.venv`). This matches Plan 1's `backend/src/app/` pattern.

---

## Task 1: Lambda handler with TDD

**Files:**
- Create: `lambda/ingest_alarm/pyproject.toml`
- Create: `lambda/ingest_alarm/src/handler.py`
- Create: `lambda/ingest_alarm/tests/__init__.py`
- Create: `lambda/ingest_alarm/tests/conftest.py`
- Create: `lambda/ingest_alarm/tests/test_handler.py`

- [ ] **Step 1: Create `lambda/ingest_alarm/pyproject.toml`**

```toml
[project]
name = "opensre-ingest-alarm"
version = "0.1.0"
description = "Lambda shim: SNS CloudWatch-alarm event -> ssm:SendCommand on OpenSRE host"
requires-python = ">=3.12"
# boto3 is provided by the Lambda Python 3.12 runtime — listed here only for local tests.
dependencies = [
    "boto3>=1.35",
]

[dependency-groups]
dev = [
    "pytest>=8",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/handler.py"]
```

- [ ] **Step 2: Sync deps**

```bash
cd lambda/ingest_alarm && uv sync
```

Expected: a `.venv/` is created and pytest is installed.

- [ ] **Step 3: Create empty test scaffolding**

```bash
mkdir -p lambda/ingest_alarm/tests
touch lambda/ingest_alarm/tests/__init__.py
```

- [ ] **Step 4: Create `lambda/ingest_alarm/tests/conftest.py`**

```python
import os
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _required_env(monkeypatch):
    """Set the env vars handler.py reads at import time."""
    monkeypatch.setenv("OPENSRE_HOST_INSTANCE_ID", "i-0123456789abcdef0")
    monkeypatch.setenv("OPENSRE_SSM_LOG_GROUP", "/aws/ssm/opensre-investigate")
    monkeypatch.setenv("SSM_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


@pytest.fixture
def fake_ssm():
    client = MagicMock()
    client.send_command.return_value = {"Command": {"CommandId": "cmd-uuid-1234"}}
    return client


@pytest.fixture
def cpu_alarm_sns_event():
    """SNS event wrapping a CloudWatch alarm message for the CPU saturation alarm."""
    cw_alarm = {
        "AlarmName": "sut-cpu-saturation",
        "AlarmDescription": "CPU >= 80% for 1 minute",
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold Crossed: 1 datapoint [99.4] was greater than the threshold (80.0).",
        "StateChangeTime": "2026-05-08T12:34:56.789+0000",
        "Region": "US East (N. Virginia)",
        "AlarmArn": "arn:aws:cloudwatch:us-east-1:111111111111:alarm:sut-cpu-saturation",
        "Trigger": {
            "MetricName": "CPUUtilization",
            "Namespace": "AWS/ECS",
            "Statistic": "Average",
            "Dimensions": [
                {"name": "ClusterName", "value": "opensre-demo"},
                {"name": "ServiceName", "value": "opensre-demo-sut"},
            ],
            "Period": 60,
            "EvaluationPeriods": 1,
            "Threshold": 80.0,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
        },
    }
    import json
    return {
        "Records": [
            {
                "EventSource": "aws:sns",
                "Sns": {
                    "Type": "Notification",
                    "Subject": "ALARM: \"sut-cpu-saturation\"",
                    "Message": json.dumps(cw_alarm),
                    "Timestamp": "2026-05-08T12:34:56.789Z",
                },
            }
        ]
    }


@pytest.fixture
def db_error_alarm_sns_event():
    cw_alarm = {
        "AlarmName": "sut-db-connection-errors",
        "AlarmDescription": "DB connection errors >= 1 in 1 minute",
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold Crossed: 1 datapoint [3.0] was greater than the threshold (1.0).",
        "StateChangeTime": "2026-05-08T13:00:00.000+0000",
        "Region": "US East (N. Virginia)",
        "AlarmArn": "arn:aws:cloudwatch:us-east-1:111111111111:alarm:sut-db-connection-errors",
        "Trigger": {
            "MetricName": "DBConnectionErrors",
            "Namespace": "OpenSRE/SUT",
            "Statistic": "Sum",
            "Dimensions": [],
            "Period": 60,
            "EvaluationPeriods": 1,
            "Threshold": 1.0,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
        },
    }
    import json
    return {
        "Records": [
            {
                "EventSource": "aws:sns",
                "Sns": {
                    "Subject": "ALARM: \"sut-db-connection-errors\"",
                    "Message": json.dumps(cw_alarm),
                },
            }
        ]
    }
```

- [ ] **Step 5: Write failing tests**

Create `lambda/ingest_alarm/tests/test_handler.py`:

```python
import base64
import json
from unittest.mock import patch

import pytest


def test_cpu_alarm_invokes_ssm_send_command(cpu_alarm_sns_event, fake_ssm):
    with patch("handler.ssm", fake_ssm):
        import handler
        result = handler.handler(cpu_alarm_sns_event, None)

    fake_ssm.send_command.assert_called_once()
    kwargs = fake_ssm.send_command.call_args.kwargs

    assert kwargs["InstanceIds"] == ["i-0123456789abcdef0"]
    assert kwargs["DocumentName"] == "AWS-RunShellScript"
    assert kwargs["TimeoutSeconds"] == 600
    assert kwargs["CloudWatchOutputConfig"] == {
        "CloudWatchLogGroupName": "/aws/ssm/opensre-investigate",
        "CloudWatchOutputEnabled": True,
    }

    commands = kwargs["Parameters"]["commands"]
    assert len(commands) == 3
    assert commands[0].startswith("echo ")
    assert "| base64 -d > /tmp/alert-" in commands[0]
    assert commands[1] == "set -a; . /etc/opensre/.env; set +a"
    assert commands[2].startswith("/usr/local/bin/opensre investigate -i /tmp/alert-")
    assert commands[0].split()[1] != ""  # base64 payload is non-empty

    assert result["commandId"] == "cmd-uuid-1234"
    assert result["alarmName"] == "sut-cpu-saturation"
    assert result["invocationId"]


def test_cpu_alarm_payload_has_ecs_resource(cpu_alarm_sns_event, fake_ssm):
    with patch("handler.ssm", fake_ssm):
        import handler
        handler.handler(cpu_alarm_sns_event, None)

    payload_b64 = fake_ssm.send_command.call_args.kwargs["Parameters"]["commands"][0].split()[1]
    payload = json.loads(base64.b64decode(payload_b64))

    assert payload["source"] == "aws-cloudwatch"
    assert payload["alert_name"] == "sut-cpu-saturation"
    assert payload["state"] == "ALARM"
    assert payload["resource"]["type"] == "ecs-service"
    assert payload["resource"]["cluster"] == "opensre-demo"
    assert payload["resource"]["service"] == "opensre-demo-sut"
    assert payload["metric"]["namespace"] == "AWS/ECS"
    assert payload["metric"]["name"] == "CPUUtilization"
    assert payload["metric"]["threshold"] == 80.0
    assert payload["metric"]["period_seconds"] == 60
    assert "raw_sns_message" in payload
    assert payload["raw_sns_message"]["AlarmName"] == "sut-cpu-saturation"


def test_db_error_alarm_payload_has_rds_resource(db_error_alarm_sns_event, fake_ssm):
    with patch("handler.ssm", fake_ssm):
        import handler
        handler.handler(db_error_alarm_sns_event, None)

    payload_b64 = fake_ssm.send_command.call_args.kwargs["Parameters"]["commands"][0].split()[1]
    payload = json.loads(base64.b64decode(payload_b64))

    assert payload["alert_name"] == "sut-db-connection-errors"
    assert payload["resource"]["type"] == "rds-instance"
    assert payload["metric"]["namespace"] == "OpenSRE/SUT"
    assert payload["metric"]["name"] == "DBConnectionErrors"


def test_handler_generates_unique_invocation_ids(cpu_alarm_sns_event, fake_ssm):
    with patch("handler.ssm", fake_ssm):
        import handler
        ids = {handler.handler(cpu_alarm_sns_event, None)["invocationId"] for _ in range(5)}
    assert len(ids) == 5
```

- [ ] **Step 6: Run the tests to verify they fail**

```bash
cd lambda/ingest_alarm && uv run pytest -v
```

Expected: ImportError or similar — `handler` doesn't exist yet.

- [ ] **Step 7: Create `lambda/ingest_alarm/src/handler.py`**

```python
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
        # Custom metric from the log filter — there's only one RDS instance in the demo.
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
            "value_at_breach": None,  # CW alarm payloads don't always include the breaching datapoint
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

    # Source /etc/opensre/.env so OpenSRE's built-in Telegram integration sees
    # TELEGRAM_BOT_TOKEN + TELEGRAM_DEFAULT_CHAT_ID — SSM RunCommand uses a
    # non-login shell that doesn't auto-source /etc/profile.d/.
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
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
cd lambda/ingest_alarm && uv run pytest -v
```

Expected: 4 passed.

- [ ] **Step 9: Commit**

```bash
git add lambda/ingest_alarm/
git commit -m "feat(lambda): add ingest_alarm handler + tests"
```

---

## Task 2: SNS topic + Lambda log group + outputs

**Files:**
- Create: `infra/alarms.tf` (initial — SNS topic only; metric filter and alarms in later tasks)
- Modify: `infra/outputs.tf` (append SNS topic ARN)

- [ ] **Step 1: Create `infra/alarms.tf`**

```terraform
# SNS topic that CloudWatch alarms publish to. Lambda is the only subscription
# (added in Task 5). The Lambda log group is created here so retention is set
# explicitly rather than auto-created with default infinite retention on first
# invocation.

resource "aws_sns_topic" "opensre_alarms" {
  name = "${var.project}-alarms"
  tags = { Name = "${var.project}-alarms" }
}

resource "aws_cloudwatch_log_group" "ingest_alarm" {
  name              = "/aws/lambda/ingest_alarm"
  retention_in_days = 7
  tags              = { Name = "${var.project}-ingest-alarm-logs" }
}
```

- [ ] **Step 2: Append to `infra/outputs.tf`**

```terraform
output "alarms_sns_topic_arn" {
  description = "SNS topic CloudWatch alarms publish to."
  value       = aws_sns_topic.opensre_alarms.arn
}
```

- [ ] **Step 3: Validate + plan**

```bash
cd infra && terraform fmt && terraform validate && terraform plan -out=plan-3-2.tfplan
```

Expected: 2 resources to add (SNS topic + Lambda log group). 1 output added.

- [ ] **Step 4: Commit**

```bash
git add infra/alarms.tf infra/outputs.tf
git commit -m "feat(infra): add opensre-alarms SNS topic + ingest_alarm log group"
rm -f infra/plan-3-2.tfplan
```

---

## Task 3: CloudWatch Logs metric filter for DB connection errors

**Files:**
- Modify: `infra/alarms.tf` (append metric filter resource)

- [ ] **Step 1: Append to `infra/alarms.tf`**

Add at end of `infra/alarms.tf`:

```terraform
# Metric filter on the SUT log group. Pattern (per spec §4) ORs three known
# Postgres connection-error substrings. Each match emits 1 to the custom metric
# OpenSRE/SUT/DBConnectionErrors. Alarm 2 watches this metric.
#
# CloudWatch Logs filter syntax: each `?"<substring>"` is an OR-match. Multiple
# `?...` patterns are OR'd together. See:
# https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntax.html
resource "aws_cloudwatch_log_metric_filter" "db_connection_errors" {
  name           = "${var.project}-db-connection-errors"
  log_group_name = aws_cloudwatch_log_group.sut.name
  pattern        = "?\"could not connect to server\" ?\"connection timeout\" ?\"OperationalError\""

  metric_transformation {
    name      = "DBConnectionErrors"
    namespace = "OpenSRE/SUT"
    value     = "1"
    # Default to 0 so the alarm doesn't sit in INSUFFICIENT_DATA forever.
    default_value = "0"
    unit          = "Count"
  }
}
```

- [ ] **Step 2: Validate + plan**

```bash
cd infra && terraform fmt && terraform validate && terraform plan -out=plan-3-3.tfplan
```

Expected: cumulative diff now adds `aws_cloudwatch_log_metric_filter.db_connection_errors`.

- [ ] **Step 3: Commit**

```bash
git add infra/alarms.tf
git commit -m "feat(infra): add sut-db-connection-errors metric filter"
rm -f infra/plan-3-3.tfplan
```

---

## Task 4: Two CloudWatch alarms

**Files:**
- Modify: `infra/alarms.tf` (append two alarm resources)
- Modify: `infra/outputs.tf` (append alarm names)

- [ ] **Step 1: Append to `infra/alarms.tf`**

```terraform
# Alarm 1: ECS service-level CPUUtilization >= 80% for 1 datapoint of 1 min.
# AWS/ECS emits service-level CPUUtilization by default — no Container Insights needed.
resource "aws_cloudwatch_metric_alarm" "sut_cpu_saturation" {
  alarm_name          = "sut-cpu-saturation"
  alarm_description   = "SUT ECS service CPU utilization >= 80% for 1 minute. Plan 3."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.demo.name
    ServiceName = aws_ecs_service.sut.name
  }

  alarm_actions = [aws_sns_topic.opensre_alarms.arn]
  ok_actions    = [] # demo: don't fire OK transitions
  tags          = { Name = "${var.project}-sut-cpu-saturation" }
}

# Alarm 2: custom metric from the log filter; >= 1 over 1 min.
resource "aws_cloudwatch_metric_alarm" "sut_db_connection_errors" {
  alarm_name          = "sut-db-connection-errors"
  alarm_description   = "SUT log group emitted >= 1 DB connection error in 1 minute. Plan 3."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "DBConnectionErrors"
  namespace           = "OpenSRE/SUT"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.opensre_alarms.arn]
  ok_actions    = []
  tags          = { Name = "${var.project}-sut-db-connection-errors" }

  depends_on = [aws_cloudwatch_log_metric_filter.db_connection_errors]
}
```

- [ ] **Step 2: Append to `infra/outputs.tf`**

```terraform
output "alarm_cpu_name" {
  description = "ECS CPU saturation alarm — pass to `aws cloudwatch set-alarm-state` for manual smoke tests."
  value       = aws_cloudwatch_metric_alarm.sut_cpu_saturation.alarm_name
}

output "alarm_db_errors_name" {
  description = "DB connection-errors alarm — pass to `aws cloudwatch set-alarm-state`."
  value       = aws_cloudwatch_metric_alarm.sut_db_connection_errors.alarm_name
}
```

- [ ] **Step 3: Validate + plan**

```bash
cd infra && terraform fmt && terraform validate && terraform plan -out=plan-3-4.tfplan
```

Expected: 2 alarms to add, 2 outputs.

- [ ] **Step 4: Commit**

```bash
git add infra/alarms.tf infra/outputs.tf
git commit -m "feat(infra): add sut-cpu-saturation + sut-db-connection-errors alarms"
rm -f infra/plan-3-4.tfplan
```

---

## Task 5: Lambda Terraform — function, IAM, SNS subscription

**Files:**
- Create: `infra/lambda.tf`
- Modify: `infra/outputs.tf` (append Lambda function name)

This task references `aws_instance.opensre[0].id` directly, which means **`var.opensre_host_enabled` must be `true`** before applying this task. The plan errors out otherwise — that's intentional; an alert pipeline without a host has no useful end state.

- [ ] **Step 1: Create `infra/lambda.tf`**

```terraform
# Lambda shim: SNS event -> normalise into OpenSRE alert envelope -> ssm:SendCommand
# against the Plan-2 OpenSRE host.

# --- Zip the source ---
data "archive_file" "ingest_alarm" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/ingest_alarm/src"
  output_path = "${path.module}/build/ingest_alarm.zip"
}

# --- IAM: assume role ---
data "aws_iam_policy_document" "ingest_alarm_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest_alarm" {
  name               = "${var.project}-ingest-alarm"
  assume_role_policy = data.aws_iam_policy_document.ingest_alarm_assume.json
}

# Basic execution: CloudWatch Logs.
resource "aws_iam_role_policy_attachment" "ingest_alarm_basic" {
  role       = aws_iam_role.ingest_alarm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Inline: ssm:SendCommand scoped to the OpenSRE host instance ARN + AWS-RunShellScript document.
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ingest_alarm_ssm" {
  statement {
    sid     = "SsmSendCommandToOpensreHost"
    effect  = "Allow"
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.opensre[0].id}",
      "arn:aws:ssm:${var.region}::document/AWS-RunShellScript",
    ]
  }
}

resource "aws_iam_role_policy" "ingest_alarm_ssm" {
  name   = "${var.project}-ingest-alarm-ssm"
  role   = aws_iam_role.ingest_alarm.id
  policy = data.aws_iam_policy_document.ingest_alarm_ssm.json
}

# --- The function ---
resource "aws_lambda_function" "ingest_alarm" {
  function_name    = "${var.project}-ingest-alarm"
  role             = aws_iam_role.ingest_alarm.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.ingest_alarm.output_path
  source_code_hash = data.archive_file.ingest_alarm.output_base64sha256

  memory_size = 256
  timeout     = 30

  environment {
    variables = {
      OPENSRE_HOST_INSTANCE_ID = aws_instance.opensre[0].id
      OPENSRE_SSM_LOG_GROUP    = aws_cloudwatch_log_group.opensre_investigate.name
      SSM_TIMEOUT_SECONDS      = "600"
    }
  }

  # Use the pre-created log group so retention is honoured on the first invocation.
  depends_on = [
    aws_cloudwatch_log_group.ingest_alarm,
    aws_iam_role_policy.ingest_alarm_ssm,
    aws_iam_role_policy_attachment.ingest_alarm_basic,
  ]

  tags = { Name = "${var.project}-ingest-alarm" }
}

# --- SNS -> Lambda subscription ---
resource "aws_lambda_permission" "allow_sns" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_alarm.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.opensre_alarms.arn
}

resource "aws_sns_topic_subscription" "lambda" {
  topic_arn = aws_sns_topic.opensre_alarms.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.ingest_alarm.arn

  depends_on = [aws_lambda_permission.allow_sns]
}
```

- [ ] **Step 2: Append to `infra/outputs.tf`**

```terraform
output "ingest_alarm_function_name" {
  description = "Lambda function name. Use for `aws logs tail /aws/lambda/<this>` and manual invokes."
  value       = aws_lambda_function.ingest_alarm.function_name
}
```

- [ ] **Step 3: Add `infra/build/` to `.gitignore`**

The `archive_file` writes its zip to `infra/build/ingest_alarm.zip`. Append to `infra/.gitignore` (create if missing — there's already one per Plan 1):

```text
build/
```

- [ ] **Step 4: Validate + plan**

```bash
cd infra && terraform fmt && terraform validate && terraform plan -out=plan-3-5.tfplan
```

Expected diff:
- `data.archive_file.ingest_alarm` (data source — no resource creation, but the zip is built)
- `aws_iam_role.ingest_alarm`
- `aws_iam_role_policy_attachment.ingest_alarm_basic`
- `aws_iam_role_policy.ingest_alarm_ssm`
- `aws_lambda_function.ingest_alarm`
- `aws_lambda_permission.allow_sns`
- `aws_sns_topic_subscription.lambda`

If the plan errors with `aws_instance.opensre[0]: index out of range`, your `opensre_host_enabled` is `false`. Fix Plan 2 first (Task 6 of Plan 2 — flip to `true`).

- [ ] **Step 5: Commit**

```bash
git add infra/lambda.tf infra/outputs.tf infra/.gitignore
git commit -m "feat(infra): add ingest_alarm Lambda + IAM + SNS subscription"
rm -f infra/plan-3-5.tfplan
```

---

## Task 6: Apply + smoke tests for both alarms

This applies all Plan-3 resources in one shot, then verifies each alarm end-to-end via `aws cloudwatch set-alarm-state`. No FIS yet.

- [ ] **Step 1: Apply**

```bash
cd infra && terraform apply
```

Expected: ~9 resources to add. Confirm with `yes`. Apply takes ~30 s.

- [ ] **Step 2: Capture outputs**

```bash
cd infra
ALARM_CPU=$(terraform output -raw alarm_cpu_name)
ALARM_DB=$(terraform output -raw alarm_db_errors_name)
LAMBDA=$(terraform output -raw ingest_alarm_function_name)
SSM_LOG=$(terraform output -raw opensre_ssm_log_group)
REGION=$(terraform output -raw aws_region)
echo "$ALARM_CPU"; echo "$ALARM_DB"; echo "$LAMBDA"
```

Expected:
```
sut-cpu-saturation
sut-db-connection-errors
opensre-demo-ingest-alarm
```

- [ ] **Step 3: Smoke test 1 — CPU alarm**

Force the alarm to ALARM state. CloudWatch publishes to SNS, Lambda fires, SSM RunCommand sources Plan 2's `/etc/opensre/.env` and runs `opensre investigate`, and OpenSRE's built-in Telegram integration posts the RCA.

```bash
aws cloudwatch set-alarm-state --region "$REGION" \
  --alarm-name "$ALARM_CPU" --state-value ALARM \
  --state-reason "Plan-3 manual smoke: simulating CPU saturation"
echo "Alarm forced. Waiting for the chain to run..."
```

Tail the Lambda log group to confirm invocation (within ~5 s of the alarm transition):

```bash
aws logs tail /aws/lambda/ingest_alarm --since 2m --region "$REGION" --follow
```

Expected log lines (Ctrl-C to stop following):
- `Received event: {"Records":[...]}`
- `ssm:SendCommand instance=i-... alarm=sut-cpu-saturation invocation=<uuid>`
- `ssm:SendCommand sent commandId=<uuid> alarm=sut-cpu-saturation invocation=<uuid>`

Then tail the SSM log group for the `opensre investigate` output (within ~30–180 s):

```bash
aws logs tail "$SSM_LOG" --since 5m --region "$REGION" --follow
```

Expected: OpenSRE's reasoning trace (alert echo, CW metric queries, log filters, RCA summary). The Telegram POST itself is performed inside `opensre investigate` via the built-in messaging integration, so its Bot API response isn't always echoed to stdout — confirm delivery by checking the group directly.

Open Telegram. Expected: an `[OpenSRE RCA]`-prefixed message in the configured group, referencing `sut-cpu-saturation`.

- [ ] **Step 4: Smoke test 2 — DB-connection-errors alarm**

```bash
aws cloudwatch set-alarm-state --region "$REGION" \
  --alarm-name "$ALARM_DB" --state-value ALARM \
  --state-reason "Plan-3 manual smoke: simulating DB connection errors"
```

Repeat the log-tailing checks from Step 3. Expected RCA in Telegram referencing `sut-db-connection-errors` and the RDS instance.

- [ ] **Step 5: Bonus — log-pattern smoke (optional, more realistic)**

To validate the metric filter end-to-end (rather than just forcing the alarm state), inject a fake error log into the SUT log group:

```bash
LOG_GROUP=$(cd infra && terraform output -raw sut_log_group_name 2>/dev/null || echo "/ecs/opensre-demo-sut")
STREAM="plan3-smoke-$(date +%s)"
aws logs create-log-stream --log-group-name "$LOG_GROUP" --log-stream-name "$STREAM" --region "$REGION"
aws logs put-log-events \
  --log-group-name "$LOG_GROUP" --log-stream-name "$STREAM" --region "$REGION" \
  --log-events "timestamp=$(date +%s)000,message='OperationalError: could not connect to server: Connection refused (Plan-3 smoke)'"
echo "Log injected. Wait ~60-120s for CW to evaluate the metric filter..."
```

Expected: within ~2 min, the `sut-db-connection-errors` alarm transitions OK→ALARM naturally (no `set-alarm-state` needed), Lambda fires, RCA arrives in Telegram.

If your SUT log group output isn't named `sut_log_group_name`, the path `/ecs/opensre-demo-sut` is what Plan 1's `infra/ecs_service.tf` uses.

- [ ] **Step 6: Reset alarms (optional cleanup)**

```bash
aws cloudwatch set-alarm-state --region "$REGION" --alarm-name "$ALARM_CPU" --state-value OK --state-reason "smoke complete"
aws cloudwatch set-alarm-state --region "$REGION" --alarm-name "$ALARM_DB"  --state-value OK --state-reason "smoke complete"
```

These won't fire OK actions (we set `ok_actions = []` in Task 4), so this is purely cosmetic for the AWS console.

- [ ] **Step 7: Nothing to commit** — this is verification only.

---

## Task 7: Documentation — main README update

**Files:**
- Modify: `README.md` (append a "Plan 3 quick start" section between Plan 2 and Teardown)

- [ ] **Step 1: Append to `README.md`**

Find the "## Teardown" line in `README.md`. Insert this block immediately above it:

````markdown
## Plan 3 quick start (alert pipeline)

Builds on Plan 2. Wires CloudWatch alarms → SNS → Lambda → SSM → OpenSRE host (Plan 2). After this plan, manually setting an alarm to ALARM produces a real RCA in Telegram. Plan 4 adds the FIS chaos triggers.

```bash
# 0. Plan 2 must be applied with opensre_host_enabled = true. Confirm with:
cd infra && terraform output opensre_host_instance_id   # prints i-...

# 1. Apply Plan 3 resources (additive on top of Plans 1-2).
terraform apply

# 2. Smoke test the CPU alarm:
ALARM_CPU=$(terraform output -raw alarm_cpu_name)
REGION=$(terraform output -raw aws_region)
aws cloudwatch set-alarm-state --region "$REGION" \
  --alarm-name "$ALARM_CPU" --state-value ALARM \
  --state-reason "Plan-3 smoke"

# 3. Watch the chain react.
aws logs tail /aws/lambda/ingest_alarm --since 2m --region "$REGION" --follow
aws logs tail "$(terraform output -raw opensre_ssm_log_group)" --since 5m --region "$REGION" --follow

# 4. Repeat for the DB-errors alarm:
ALARM_DB=$(terraform output -raw alarm_db_errors_name)
aws cloudwatch set-alarm-state --region "$REGION" \
  --alarm-name "$ALARM_DB" --state-value ALARM \
  --state-reason "Plan-3 smoke"
```

Both smoke tests should produce RCAs in the configured Telegram group within ~3 minutes of the alarm transition.
````

- [ ] **Step 2: Verify README still renders cleanly**

```bash
grep -c '^```' README.md
```

Expected: an even number.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(plan-3): add alert-pipeline quick-start"
```

---

## Final validation checklist

- [ ] `cd lambda/ingest_alarm && uv run pytest -v` — 4 tests pass.
- [ ] `cd infra && terraform plan` — **No changes**.
- [ ] `terraform output alarms_sns_topic_arn` returns an SNS ARN.
- [ ] `terraform output ingest_alarm_function_name` returns `opensre-demo-ingest-alarm`.
- [ ] `aws lambda get-function --function-name $(terraform output -raw ingest_alarm_function_name) --region $(terraform output -raw aws_region) --query Configuration.Environment.Variables.OPENSRE_HOST_INSTANCE_ID --output text` matches `terraform output -raw opensre_host_instance_id`.
- [ ] Forcing each alarm via `aws cloudwatch set-alarm-state … --state-value ALARM` produces a Lambda log entry within ~5 s, an SSM log entry within ~30 s, and a Telegram RCA within ~3 min.
- [ ] The metric filter smoke test (Task 6 Step 5) produces an RCA without `set-alarm-state` (i.e. the natural log-pattern → metric → alarm pipeline works).
- [ ] CloudWatch Logs Insights query against `/aws/lambda/ingest_alarm` over the last 30 min shows the `ssm:SendCommand sent commandId=...` line.

---

## Teardown notes

To reduce costs without destroying everything:

```bash
cd infra
sed -i.bak 's/opensre_host_enabled = true/opensre_host_enabled = false/' terraform.tfvars
rm -f terraform.tfvars.bak
terraform apply
```

This destroys the OpenSRE EC2 (Plan 2 toggle) and **also** the Lambda + IAM (because `lambda.tf` references `aws_instance.opensre[0]`, so flipping the host off forces the dependent Lambda to error). To keep alarms but ditch Lambda, you'd need to add a `count = var.opensre_host_enabled ? 1 : 0` guard to the Lambda resources — out of scope for this plan; the cleaner pattern is "all-or-nothing per-Plan-2-toggle".

To fully tear down: `terraform destroy` (wipes Plans 1, 2, 3).

---

## What this plan does NOT do (deferred to Plan 4)

- ❌ FIS experiment templates (`cpu-stress-ecs`, `rds-reboot`).
- ❌ ECS task tagging required for `aws:ecs:task-cpu-stress` targeting.
- ❌ The `scripts/start_chaos.sh` operator wrapper.
- ❌ End-to-end demo driven by `aws fis start-experiment`.

Until Plan 4 lands, the alert pipeline is verifiable only via `aws cloudwatch set-alarm-state` and the natural log-pattern injection in Task 6 Step 5. That's the right unit of verification for this plan — it proves the alarm-to-Telegram chain is correct, independent of how alarms come to fire.

---

*End of Plan 3.*
