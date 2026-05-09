import os
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _required_env(monkeypatch):
    """Set the env vars handler.py reads at import time and ensure handler is importable."""
    monkeypatch.setenv("OPENSRE_HOST_INSTANCE_ID", "i-0123456789abcdef0")
    monkeypatch.setenv("OPENSRE_SSM_LOG_GROUP", "/aws/ssm/opensre-investigate")
    monkeypatch.setenv("SSM_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    # Ensure handler module is imported with a mocked boto3 client so the
    # module-level `ssm = boto3.client("ssm")` doesn't require real AWS creds.
    if "handler" not in sys.modules:
        with patch("boto3.client", return_value=MagicMock()):
            import handler  # noqa: F401


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
