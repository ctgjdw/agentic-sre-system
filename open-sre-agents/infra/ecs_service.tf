resource "aws_cloudwatch_log_group" "sut" {
  name              = "/ecs/${var.project}-sut"
  retention_in_days = 7
}

locals {
  sut_image = "${aws_ecr_repository.sut.repository_url}:latest"

  sut_database_url = "postgresql://opensre:${var.db_password}@${aws_db_instance.demo.address}:5432/opensre_demo"
  ui_origin        = "http://${aws_s3_bucket_website_configuration.ui.website_endpoint}"
}

resource "aws_ecs_task_definition" "sut" {
  family             = "${var.project}-sut"
  network_mode       = "bridge"
  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  cpu                = "256"
  memory             = "256"

  container_definitions = jsonencode([
    {
      name      = "sut"
      image     = local.sut_image
      essential = true
      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "DATABASE_URL", value = local.sut_database_url },
        { name = "CORS_ORIGIN", value = local.ui_origin },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.sut.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "sut"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "sut" {
  name            = "${var.project}-sut"
  cluster         = aws_ecs_cluster.demo.id
  task_definition = aws_ecs_task_definition.sut.arn
  desired_count   = var.sut_desired_count
  launch_type     = "EC2"

  # Allow Terraform to roll the deployment on task-definition or env changes.
  force_new_deployment = true

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  # The SUT EC2 must be registered to the cluster before this service tries to place tasks.
  depends_on = [aws_instance.sut]
}
