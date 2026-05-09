# Empty Secrets Manager shells. Values are populated manually after the first
# `terraform apply` via `aws secretsmanager put-secret-value` so credentials
# never enter the repo or terraform state files.

resource "aws_secretsmanager_secret" "anthropic" {
  name                    = "opensre/anthropic_api_key"
  description             = "OpenSRE host: Anthropic API key for the agent's LLM calls."
  recovery_window_in_days = 0 # demo: allow immediate recreation on destroy
  tags                    = { Name = "${var.project}-anthropic-api-key" }
}

resource "aws_secretsmanager_secret" "telegram" {
  name                    = "opensre/telegram_bot_token"
  description             = "OpenSRE host: Telegram bot token for posting RCA messages via Bot API."
  recovery_window_in_days = 0
  tags                    = { Name = "${var.project}-telegram-bot-token" }
}
