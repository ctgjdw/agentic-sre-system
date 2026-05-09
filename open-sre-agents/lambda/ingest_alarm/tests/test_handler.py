import base64
import json
from unittest.mock import patch


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
    assert len(commands) == 4
    assert commands[0].startswith("echo ")
    assert "| base64 -d > /tmp/alert-" in commands[0]
    assert commands[1] == "set -a; . /etc/opensre/.env; set +a"
    assert "AWS_ACCESS_KEY_ID" in commands[2]
    assert commands[3].startswith("/usr/local/bin/opensre investigate -i /tmp/alert-")
    assert commands[0].split()[1] != ""  # base64 payload is non-empty

    assert result["commandId"] == "cmd-uuid-1234"
    assert result["alarmName"] == "sut-cpu-saturation"
    assert result["invocationId"]


def test_cpu_alarm_payload_is_grafana_format(cpu_alarm_sns_event, fake_ssm):
    with patch("handler.ssm", fake_ssm):
        import handler
        handler.handler(cpu_alarm_sns_event, None)

    payload_b64 = fake_ssm.send_command.call_args.kwargs["Parameters"]["commands"][0].split()[1]
    payload = json.loads(base64.b64decode(payload_b64))

    assert payload["alert_name"] == "sut-cpu-saturation"
    assert payload["pipeline_name"] == "opensre-demo-sut"
    assert payload["severity"] == "critical"
    assert payload["state"] == "alerting"
    assert payload["version"] == "4"
    assert len(payload["alerts"]) == 1

    alert = payload["alerts"][0]
    assert alert["status"] == "firing"
    assert alert["labels"]["alertname"] == "sut-cpu-saturation"
    assert alert["labels"]["pipeline_name"] == "opensre-demo-sut"

    annotations = payload["commonAnnotations"]
    assert annotations["context_sources"] == "cloudwatch"
    assert annotations["cloudwatch_log_group"] == "/ecs/opensre-demo-sut"
    assert annotations["cloudwatch_region"] == "us-east-1"
    assert annotations["ecs_cluster"] == "opensre-demo"
    assert annotations["ecs_service"] == "opensre-demo-sut"
    assert "CPU" in annotations["summary"]


def test_db_error_alarm_payload_has_rds_annotations(db_error_alarm_sns_event, fake_ssm):
    with patch("handler.ssm", fake_ssm):
        import handler
        handler.handler(db_error_alarm_sns_event, None)

    payload_b64 = fake_ssm.send_command.call_args.kwargs["Parameters"]["commands"][0].split()[1]
    payload = json.loads(base64.b64decode(payload_b64))

    assert payload["alert_name"] == "sut-db-connection-errors"
    annotations = payload["commonAnnotations"]
    assert annotations["context_sources"] == "cloudwatch"
    assert annotations["rds_instance"] == "opensre-demo-db"
    assert "DB connection errors" in annotations["summary"]


def test_handler_generates_unique_invocation_ids(cpu_alarm_sns_event, fake_ssm):
    with patch("handler.ssm", fake_ssm):
        import handler
        ids = {handler.handler(cpu_alarm_sns_event, None)["invocationId"] for _ in range(5)}
    assert len(ids) == 5
