resource "aws_sns_topic" "opensre_alarms" {
  name = "${var.project}-alarms"
  tags = { Name = "${var.project}-alarms" }
}

resource "aws_cloudwatch_log_group" "ingest_alarm" {
  name              = "/aws/lambda/ingest_alarm"
  retention_in_days = 7
  tags              = { Name = "${var.project}-ingest-alarm-logs" }
}
