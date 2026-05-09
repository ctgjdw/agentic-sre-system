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
