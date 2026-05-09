resource "aws_sns_topic" "opensre_alarms" {
  name = "${var.project}-alarms"
  tags = { Name = "${var.project}-alarms" }
}

resource "aws_cloudwatch_log_group" "ingest_alarm" {
  name              = "/aws/lambda/ingest_alarm"
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
