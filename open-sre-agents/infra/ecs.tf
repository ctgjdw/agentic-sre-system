# --- Cluster ---

resource "aws_ecs_cluster" "demo" {
  name = var.project
}

# --- IAM: ECS task execution role (pulls image from ECR, ships logs) ---

data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.project}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# --- IAM: SUT EC2 instance role (joins ECS, ships logs, SSM-managed for port-forward) ---

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sut_host" {
  name               = "${var.project}-sut-host"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "sut_host_ecs" {
  role       = aws_iam_role.sut_host.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "sut_host_ssm" {
  role       = aws_iam_role.sut_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "sut_host" {
  name = "${var.project}-sut-host"
  role = aws_iam_role.sut_host.name
}

# --- ECS-optimised AMI lookup ---

data "aws_ssm_parameter" "ecs_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id"
}

# --- SUT EC2 host (registers itself to the ECS cluster) ---

resource "aws_eip" "sut" {
  domain = "vpc"
  tags   = { Name = "${var.project}-sut-eip" }
}

resource "aws_instance" "sut" {
  ami                    = data.aws_ssm_parameter.ecs_ami.value
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.sut_host.id]
  iam_instance_profile   = aws_iam_instance_profile.sut_host.name
  monitoring             = true

  user_data = <<-EOT
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.demo.name}" >> /etc/ecs/ecs.config
    echo "ECS_AVAILABLE_LOGGING_DRIVERS=[\"json-file\",\"awslogs\"]" >> /etc/ecs/ecs.config
  EOT

  tags = {
    Name    = "${var.project}-sut-host"
    Project = var.project
  }
}

resource "aws_eip_association" "sut" {
  instance_id   = aws_instance.sut.id
  allocation_id = aws_eip.sut.id
}
