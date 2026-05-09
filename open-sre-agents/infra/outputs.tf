output "sut_public_ip" {
  description = "Stable EIP attached to the SUT EC2 host."
  value       = aws_eip.sut.public_ip
}

output "sut_api_url" {
  description = "Backend base URL for the UI's NEXT_PUBLIC_API_URL."
  value       = "http://${aws_eip.sut.public_ip}:8080"
}

output "sut_instance_id" {
  description = "EC2 instance ID — pass to `aws ssm start-session` for port-forwarding."
  value       = aws_instance.sut.id
}

output "rds_endpoint" {
  description = "RDS endpoint host:port."
  value       = aws_db_instance.demo.endpoint
}

output "rds_address" {
  description = "RDS endpoint host (no port)."
  value       = aws_db_instance.demo.address
}

output "ecr_repository_url" {
  description = "Push backend images here."
  value       = aws_ecr_repository.sut.repository_url
}

output "ui_bucket" {
  description = "Sync the Next.js export here."
  value       = aws_s3_bucket.ui.bucket
}

output "ui_website_url" {
  description = "Public S3 website URL."
  value       = "http://${aws_s3_bucket_website_configuration.ui.website_endpoint}"
}

output "anthropic_secret_id" {
  description = "Run: aws secretsmanager put-secret-value --secret-id <this> --secret-string sk-ant-..."
  value       = aws_secretsmanager_secret.anthropic.id
}

output "telegram_secret_id" {
  description = "Run: aws secretsmanager put-secret-value --secret-id <this> --secret-string <bot-token>"
  value       = aws_secretsmanager_secret.telegram.id
}

output "aws_region" {
  description = "Region resolved from var.region. Helper scripts read this output."
  value       = var.region
}

output "opensre_host_instance_id" {
  description = "Pass to `aws ssm send-command` and `aws ssm start-session`. Null when var.opensre_host_enabled = false."
  value       = var.opensre_host_enabled ? aws_instance.opensre[0].id : null
}

output "opensre_ssm_log_group" {
  description = "CloudWatch Log Group for `opensre investigate` stdout/stderr."
  value       = aws_cloudwatch_log_group.opensre_investigate.name
}

output "alarms_sns_topic_arn" {
  description = "SNS topic CloudWatch alarms publish to."
  value       = aws_sns_topic.opensre_alarms.arn
}
