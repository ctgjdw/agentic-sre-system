# CloudWatch log group for SSM RunCommand stdout/stderr from `opensre investigate`.
# Plan 3's Lambda shim and Plan 2's helper script both invoke send-command with
#   --cloud-watch-output-config CloudWatchLogGroupName=/aws/ssm/opensre-investigate
# so streams land here, one per command-id. 7-day retention per spec §4.
resource "aws_cloudwatch_log_group" "opensre_investigate" {
  name              = "/aws/ssm/opensre-investigate"
  retention_in_days = 7

  tags = { Name = "${var.project}-opensre-investigate" }
}
