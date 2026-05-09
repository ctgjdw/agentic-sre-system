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
      # Target ARN form: arn:aws:ec2:<region>:<account>:instance/<id>.
      # We allow any EC2 instance in this account/region rather than
      # hardcoding the OpenSRE host's ID, so a host-replace (Plan 4
      # Task 10's user_data_replace_on_change) doesn't require an IAM update.
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

# CPU saturation via load burst: FIS dispatches aws:ssm:send-command to the
# OpenSRE host (selected by tag Role=opensre-agent), which runs Plan-4's
# load_runner.py. The runner ramps to 200 VUs over 30 s, holds for ~150 s,
# and drives weighted REST traffic against the SUT — saturating ECS service
# CPUUtilization above 80 % from real-looking access-log evidence.
#
# The duration parameter on the FIS action is the *deadline* for the SSM
# command to complete. We give it 4 minutes (PT4M); the load runner itself
# exits at ~3 min. If the runner overruns, FIS terminates the command.
resource "aws_fis_experiment_template" "cpu_load_burst" {
  description = "Drive 200-VU mixed REST load on the SUT to trigger sut-cpu-saturation"
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

  action {
    name        = "send-load-burst"
    action_id   = "aws:ssm:send-command"
    description = "Run load_runner.py via AWS-RunShellScript on the OpenSRE host"

    parameter {
      key   = "documentArn"
      value = "arn:aws:ssm:${var.region}::document/AWS-RunShellScript"
    }
    parameter {
      key   = "duration"
      value = "PT4M"
    }
    # documentParameters value must be a JSON string per the FIS docs.
    # `commands` is a list of shell command strings to execute serially.
    parameter {
      key = "documentParameters"
      value = jsonencode({
        commands = [
          "python3 /opt/opensre/load_runner.py http://${aws_eip.sut.public_ip}:8080 --duration 180 --ramp 30 --max-vus 200 --max-id 10000"
        ]
      })
    }

    target {
      key   = "Instances"
      value = "OpenSREHost"
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
