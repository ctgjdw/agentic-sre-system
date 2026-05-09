data "archive_file" "ingest_alarm" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/ingest_alarm/src"
  output_path = "${path.module}/build/ingest_alarm.zip"
}

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

resource "aws_iam_role_policy_attachment" "ingest_alarm_basic" {
  role       = aws_iam_role.ingest_alarm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

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
      SUT_LOG_GROUP            = aws_cloudwatch_log_group.sut.name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.ingest_alarm,
    aws_iam_role_policy.ingest_alarm_ssm,
    aws_iam_role_policy_attachment.ingest_alarm_basic,
  ]

  tags = { Name = "${var.project}-ingest-alarm" }
}

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
