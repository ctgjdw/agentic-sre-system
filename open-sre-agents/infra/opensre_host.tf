# OpenSRE EC2 host — deliberately separate from the SUT host so chaos
# targeting the SUT can't take down the agent layer. SSM-only access; no
# inbound SG. Gated by var.opensre_host_enabled so secrets can be populated
# between the first apply (false) and the EC2 boot (true).

# --- IAM: assume-role for EC2 ---
data "aws_iam_policy_document" "opensre_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "opensre_host" {
  name               = "${var.project}-opensre-host"
  assume_role_policy = data.aws_iam_policy_document.opensre_assume.json
}

# Managed: SSM RunCommand + Session Manager target.
resource "aws_iam_role_policy_attachment" "opensre_ssm" {
  role       = aws_iam_role.opensre_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Inline: read-only AWS for OpenSRE's investigation calls (per spec §4 IAM).
data "aws_iam_policy_document" "opensre_readonly" {
  statement {
    sid    = "AwsReadOnlyForInvestigation"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "ecs:Describe*",
      "ecs:List*",
      "rds:DescribeDBInstances",
      "rds:DescribeEvents",
      "cloudwatch:GetMetricData",
      "cloudwatch:ListMetrics",
      "cloudwatch:DescribeAlarms",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:FilterLogEvents",
      "logs:GetLogEvents",
      "logs:StartQuery",
      "logs:GetQueryResults",
      "logs:StopQuery",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "opensre_readonly" {
  name   = "${var.project}-opensre-readonly"
  role   = aws_iam_role.opensre_host.id
  policy = data.aws_iam_policy_document.opensre_readonly.json
}

# Inline: read the two named secrets only.
data "aws_iam_policy_document" "opensre_secrets" {
  statement {
    sid     = "ReadDemoSecrets"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.anthropic.arn,
      aws_secretsmanager_secret.telegram.arn,
    ]
  }
}

resource "aws_iam_role_policy" "opensre_secrets" {
  name   = "${var.project}-opensre-secrets"
  role   = aws_iam_role.opensre_host.id
  policy = data.aws_iam_policy_document.opensre_secrets.json
}

resource "aws_iam_instance_profile" "opensre_host" {
  name = "${var.project}-opensre-host"
  role = aws_iam_role.opensre_host.name
}

# --- Security group: outbound only ---
resource "aws_security_group" "opensre_host" {
  name        = "${var.project}-opensre-host"
  description = "OpenSRE host: outbound only; SSM-managed (no inbound)."
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All egress (AWS APIs + Anthropic + api.telegram.org)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-opensre-host" }
}

# --- AMI: Ubuntu 24.04 LTS (glibc 2.39 + Python 3.12 needed by opensre CLI) ---
data "aws_ami" "ubuntu_2404" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# --- EC2 host (gated by var.opensre_host_enabled) ---
resource "aws_instance" "opensre" {
  count = var.opensre_host_enabled ? 1 : 0

  ami                    = data.aws_ami.ubuntu_2404.id
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.opensre_host.id]
  iam_instance_profile   = aws_iam_instance_profile.opensre_host.name

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1
  }

  user_data = templatefile("${path.module}/../opensre_host/user_data.sh.tftpl", {
    opensre_telegram_chat_id = var.opensre_telegram_chat_id
  })

  # If user_data changes, replace the instance so the new bootstrap runs.
  user_data_replace_on_change = true

  tags = {
    Name    = "${var.project}-opensre-host"
    Project = var.project
    Role    = "opensre-agent"
  }

  # Make sure the secret shells exist (so the IAM policy ARNs resolve) before
  # the EC2 boots and tries to read them.
  depends_on = [
    aws_secretsmanager_secret.anthropic,
    aws_secretsmanager_secret.telegram,
    aws_iam_role_policy.opensre_secrets,
    aws_iam_role_policy.opensre_readonly,
  ]
}
