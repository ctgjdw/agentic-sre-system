resource "aws_sns_topic" "opensre_alarms" {
  name = "${var.project}-alarms"
  tags = { Name = "${var.project}-alarms" }
}

resource "aws_cloudwatch_log_group" "ingest_alarm" {
  name              = "/aws/lambda/${var.project}-ingest-alarm"
  retention_in_days = 7
  tags              = { Name = "${var.project}-ingest-alarm-logs" }
}

resource "aws_cloudwatch_log_metric_filter" "db_connection_errors" {
  name           = "${var.project}-db-connection-errors"
  log_group_name = aws_cloudwatch_log_group.sut.name
  pattern        = "?\"could not connect to server\" ?\"connection timeout\" ?\"OperationalError\""

  metric_transformation {
    name          = "DBConnectionErrors"
    namespace     = "OpenSRE/SUT"
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "sut_cpu_saturation" {
  alarm_name          = "sut-cpu-saturation"
  alarm_description   = "SUT EC2 host CPU utilization >= 50% for 10 seconds."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 10
  statistic           = "Average"
  threshold           = 50
  treat_missing_data  = "notBreaching"

  dimensions = {
    InstanceId = aws_instance.sut.id
  }

  alarm_actions = [aws_sns_topic.opensre_alarms.arn]
  ok_actions    = []
  tags          = { Name = "${var.project}-sut-cpu-saturation" }
}

resource "aws_cloudwatch_metric_alarm" "sut_db_connection_errors" {
  alarm_name          = "sut-db-connection-errors"
  alarm_description   = "SUT log group emitted >= 1 DB connection error in 1 minute. Plan 3."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "DBConnectionErrors"
  namespace           = "OpenSRE/SUT"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.opensre_alarms.arn]
  ok_actions    = []
  tags          = { Name = "${var.project}-sut-db-connection-errors" }

  depends_on = [aws_cloudwatch_log_metric_filter.db_connection_errors]
}
