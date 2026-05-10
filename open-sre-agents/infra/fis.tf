# AWS FIS service role. Permissions per spec §4 IAM table:
#   - aws:ssm:send-command (used by cpu-load-burst): SendCommand on
#     AWS-RunShellScript + the OpenSRE host instance ARN, plus
#     ListCommands/CancelCommand and ec2:DescribeInstances for tag-resolution.
#     Mirrors AWS's managed AWSFaultInjectionSimulatorEC2Access policy,
#     scoped down to the OpenSRE host only.
#   - aws:rds:reboot-db-instances: rds:RebootDBInstance + DescribeDBInstances.

data "aws_iam_policy_document" "fis_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["fis.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fis" {
  name               = "${var.project}-fis"
  assume_role_policy = data.aws_iam_policy_document.fis_assume.json
  tags               = { Name = "${var.project}-fis" }
}

# Inline 1: SSM SendCommand on the OpenSRE host (drives cpu-load-burst).
data "aws_iam_policy_document" "fis_ssm_send_command" {
  statement {
    sid     = "SsmSendCommandToOpenSREHost"
    effect  = "Allow"
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ssm:${var.region}::document/AWS-RunShellScript",
      "arn:aws:ssm:${var.region}::document/AWSFIS-Run-CPU-Stress",
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*",
    ]
  }
  statement {
    sid    = "SsmListCancelGetCommands"
    effect = "Allow"
    actions = [
      "ssm:ListCommands",
      "ssm:CancelCommand",
      "ssm:GetCommandInvocation",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "Ec2DescribeInstancesForTagResolution"
    effect    = "Allow"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "fis_ssm_send_command" {
  name   = "${var.project}-fis-ssm-send-command"
  role   = aws_iam_role.fis.id
  policy = data.aws_iam_policy_document.fis_ssm_send_command.json
}

# Inline 2: RDS reboot action permissions.
data "aws_iam_policy_document" "fis_rds_reboot" {
  statement {
    sid     = "RdsRebootAndDescribe"
    effect  = "Allow"
    actions = ["rds:RebootDBInstance", "rds:DescribeDBInstances"]
    resources = [
      aws_db_instance.demo.arn,
      "arn:aws:rds:${var.region}:${data.aws_caller_identity.current.account_id}:db:*",
    ]
  }
}

resource "aws_iam_role_policy" "fis_rds_reboot" {
  name   = "${var.project}-fis-rds-reboot"
  role   = aws_iam_role.fis.id
  policy = data.aws_iam_policy_document.fis_rds_reboot.json
}

# CPU saturation via two parallel FIS actions:
#   1. load_runner.py on the OpenSRE host — generates realistic mixed REST
#      traffic against the SUT, filling access logs with varied source IPs and
#      weighted endpoint mix (evidence for OpenSRE's investigation).
#   2. AWSFIS-Run-CPU-Stress on the SUT EC2 host — runs stress-ng to push
#      ECS CPUUtilization over the alarm threshold. The load runner alone
#      can't saturate the single Uvicorn worker because it's I/O-bound;
#      stress-ng ensures the metric actually trips the alarm.
resource "aws_fis_experiment_template" "cpu_load_burst" {
  description = "CPU stress on SUT host + load traffic for access-log evidence"
  role_arn    = aws_iam_role.fis.arn

  stop_condition {
    source = "none"
  }

  target {
    name           = "OpenSREHost"
    resource_type  = "aws:ec2:instance"
    selection_mode = "ALL"

    resource_tag {
      key   = "Role"
      value = "opensre-agent"
    }
  }

  target {
    name           = "SUTHost"
    resource_type  = "aws:ec2:instance"
    selection_mode = "ALL"

    resource_arns = [aws_instance.sut.arn]
  }

  action {
    name        = "send-load-burst"
    action_id   = "aws:ssm:send-command"
    description = "Run load_runner.py on the OpenSRE host for access-log evidence"

    parameter {
      key   = "documentArn"
      value = "arn:aws:ssm:${var.region}::document/AWS-RunShellScript"
    }
    parameter {
      key   = "duration"
      value = "PT4M"
    }
    parameter {
      key = "documentParameters"
      value = jsonencode({
        commands = [
          "python3 /opt/opensre/load_runner.py http://${aws_eip.sut.public_ip}:8080 --duration 180 --ramp 5 --max-vus 5000 --max-id 10000"
        ]
      })
    }

    target {
      key   = "Instances"
      value = "OpenSREHost"
    }
  }

  action {
    name        = "cpu-stress-sut"
    action_id   = "aws:ssm:send-command"
    description = "Run stress-ng on the SUT EC2 host to push ECS CPUUtilization over threshold"

    parameter {
      key   = "documentArn"
      value = "arn:aws:ssm:${var.region}::document/AWSFIS-Run-CPU-Stress"
    }
    parameter {
      key   = "duration"
      value = "PT3M"
    }
    parameter {
      key = "documentParameters"
      value = jsonencode({
        DurationSeconds     = "150"
        CPU                 = "0"
        InstallDependencies = "True"
      })
    }

    target {
      key   = "Instances"
      value = "SUTHost"
    }
  }

  tags = { Name = "${var.project}-cpu-load-burst" }

  depends_on = [
    aws_iam_role_policy.fis_ssm_send_command,
    aws_instance.opensre,
  ]
}

# RDS reboot. Targets the demo RDS instance by ARN.
resource "aws_fis_experiment_template" "rds_reboot" {
  description = "Reboot the demo RDS instance to trigger sut-db-connection-errors"
  role_arn    = aws_iam_role.fis.arn

  stop_condition {
    source = "none"
  }

  target {
    name           = "DBInstances"
    resource_type  = "aws:rds:db"
    selection_mode = "ALL"

    resource_arns = [aws_db_instance.demo.arn]
  }

  action {
    name        = "reboot"
    action_id   = "aws:rds:reboot-db-instances"
    description = "Reboot the demo RDS"

    parameter {
      key   = "forceFailover"
      value = "false"
    }

    target {
      key   = "DBInstances"
      value = "DBInstances"
    }
  }

  tags = { Name = "${var.project}-rds-reboot" }

  depends_on = [aws_iam_role_policy.fis_rds_reboot]
}
