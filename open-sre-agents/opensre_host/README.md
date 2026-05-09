# OpenSRE host

The long-lived agent EC2 (`t3.micro`, AL2023) that runs `opensre investigate`
when SSM RunCommand delivers an alert payload. Provisioned by `infra/opensre_host.tf`,
bootstrapped by `user_data.sh.tftpl`.

## Files

- `user_data.sh.tftpl` — Terraform-templated bootstrap. Installs the OpenSRE
  CLI via `curl -fsSL https://install.opensre.com | bash`, fetches the two
  named secrets (`opensre/anthropic_api_key`, `opensre/telegram_bot_token`),
  writes `/etc/opensre/.env` (and a sibling `/etc/profile.d/opensre.sh` so
  every interactive shell auto-sources the env), runs
  `opensre integrations verify`, and posts a "hello" smoke message to the
  Telegram group via direct curl. Logs to `/var/log/opensre-bootstrap/bootstrap.log`.
  On success, touches `/var/log/opensre-bootstrap/bootstrap.ok`.

## How RCA delivery works

`opensre investigate -i <alert.json>` posts the RCA to Telegram via OpenSRE's
**built-in Telegram messaging integration** — no wrapper script. The integration
reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_DEFAULT_CHAT_ID` from the environment
(set by `/etc/opensre/.env` and auto-sourced by `/etc/profile.d/opensre.sh`).
Long reports are truncated to Telegram's 4 096-char per-message limit per
https://opensre.com/docs/messaging/telegram.md.

When invoking from SSM RunCommand, prefix the command with `set -a; . /etc/opensre/.env; set +a`
so the Telegram env vars are present (SSM RunCommand starts a fresh non-login
shell that doesn't auto-source `/etc/profile.d/`). Both the Plan-2 helper
(`scripts/test_opensre_alert.sh`) and Plan 3's Lambda do this.

## Inspecting the host

The host has **no inbound SG rules**. Reach it via SSM only:

```bash
HOST=$(cd infra && terraform output -raw opensre_host_instance_id)
REGION=$(cd infra && terraform output -raw aws_region)

# Interactive shell:
aws ssm start-session --target "$HOST" --region "$REGION"

# Tail bootstrap log:
aws ssm start-session --target "$HOST" --region "$REGION" \
  --document-name AWS-StartNonInteractiveCommand \
  --parameters '{"command":["sudo tail -n 200 /var/log/opensre-bootstrap/bootstrap.log"]}'

# Confirm /etc/opensre/.env exists (does not print contents):
aws ssm start-session --target "$HOST" --region "$REGION" \
  --document-name AWS-StartNonInteractiveCommand \
  --parameters '{"command":["sudo ls -l /etc/opensre/.env"]}'
```

## Re-running the bootstrap

If user-data failed (e.g. secrets were empty on first boot), recreate the instance
to retrigger user-data:

```bash
cd infra
terraform taint 'aws_instance.opensre[0]'
terraform apply
```

This destroys and recreates the EC2; the new instance runs user-data fresh.

## Updating `/etc/opensre/.env` after rotating a secret

If you `aws secretsmanager put-secret-value` to a new value, the running host
still has the old value cached in `/etc/opensre/.env`. Re-run the bootstrap-without-install
fragment manually via SSM:

```bash
HOST=$(cd infra && terraform output -raw opensre_host_instance_id)
REGION=$(cd infra && terraform output -raw aws_region)
aws ssm send-command --region "$REGION" --instance-ids "$HOST" \
  --document-name AWS-RunShellScript \
  --parameters '{"commands":[
    "AK=$(aws secretsmanager get-secret-value --secret-id opensre/anthropic_api_key --query SecretString --output text)",
    "TT=$(aws secretsmanager get-secret-value --secret-id opensre/telegram_bot_token --query SecretString --output text)",
    "TC=$(grep ^TELEGRAM_DEFAULT_CHAT_ID= /etc/opensre/.env | cut -d= -f2-)",
    "sudo install -d -m 0700 /etc/opensre",
    "sudo bash -c \"cat > /etc/opensre/.env <<E\nANTHROPIC_API_KEY=$AK\nTELEGRAM_BOT_TOKEN=$TT\nTELEGRAM_DEFAULT_CHAT_ID=$TC\nLLM_PROVIDER=anthropic\nLLM_MODEL=claude-sonnet-4-6\nE\"",
    "sudo chmod 600 /etc/opensre/.env"
  ]}'
```

Or simpler — and recommended for chat-ID changes too, since `var.opensre_telegram_chat_id` is baked into user-data: `cd infra && terraform taint 'aws_instance.opensre[0]' && terraform apply`.

## If `opensre investigate` complains "telegram not configured"

The plan assumes env-vars-only configuration is sufficient (per the integration
docs). If your OpenSRE version requires `opensre onboard` to register the
Telegram integration into a config file, run it interactively via SSM Session
Manager:

```bash
HOST=$(cd infra && terraform output -raw opensre_host_instance_id)
REGION=$(cd infra && terraform output -raw aws_region)
aws ssm start-session --target "$HOST" --region "$REGION"
# Once in the session:
sudo -i
set -a; . /etc/opensre/.env; set +a
opensre onboard
# Follow the prompts. Most fields are pre-populated from env vars.
exit
```

Then re-run `./scripts/test_opensre_alert.sh` to confirm the chain.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `bootstrap.log` ends with `FATAL: ...secret is empty` | Secret value never populated, or populated *after* user-data ran | Populate via `aws secretsmanager put-secret-value`, then `terraform taint 'aws_instance.opensre[0]' && terraform apply` |
| Bootstrap "hello" Telegram message never arrives | Bot not added to the group; chat ID wrong; token revoked | Re-invite the bot to the group; verify chat ID with `getUpdates`; rotate token if revoked; re-populate secret; `terraform taint 'aws_instance.opensre[0]' && terraform apply` |
| Bootstrap curl returns `{"ok":false,"error_code":403}` (forbidden) | Bot kicked from group / privacy/admin limits | Re-add the bot, ensure it has permission to post in the group |
| Bootstrap curl returns `{"ok":false,"error_code":400,"description":"chat not found"}` | Wrong `TELEGRAM_DEFAULT_CHAT_ID` (often missing the leading `-` for groups) | Update `var.opensre_telegram_chat_id` in tfvars and `terraform apply` (the EC2 will replace because user-data changed) |
| `opensre investigate` runs Success but no Telegram message | OpenSRE version requires `onboard` to register the integration even when env vars are set | SSM-Session in and run `opensre onboard` interactively (see "If `opensre investigate` complains" above) |
| SSM RunCommand returns `InvalidInstanceId` | Host not yet SSM-Online | Wait 1–2 min after `terraform apply`; check `aws ssm describe-instance-information` |
| `opensre investigate` takes >5 min | Long agent loop / Anthropic latency | Acceptable; spec p95 budget is ~3 min, p99 closer to 4–5 min. Hard-killed at 600 s by SSM timeout. |
