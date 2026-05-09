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
