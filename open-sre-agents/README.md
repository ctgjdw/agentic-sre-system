# OpenSRE MVP

A demo that proves the loop: chaos event -> CloudWatch alarm -> OpenSRE investigates -> RCA in Slack.

This branch ships **Plan 1 only** -- the demo backbone (UI + SUT + RDS). Plans 2-4 add the OpenSRE host, alert pipeline, and FIS chaos.

## Plan 1 quick start

```bash
# 0. Prereqs: AWS CLI v2, Terraform 1.9+, Docker, uv, Node 20+, session-manager-plugin

# 1. Configure infra/terraform.tfvars (copy from .example, set db_password and ui_bucket_suffix)

# 2. Provision (with sut_desired_count = 0 for the first apply)
cd infra && terraform init && terraform apply

# 3. Build & push the backend image
export ECR_URL=$(terraform output -raw ecr_repository_url)
export AWS_REGION=$(grep -E '^region' terraform.tfvars 2>/dev/null | sed -E 's/.*= *"(.*)"/\1/' || echo us-east-1)
export AWS_REGION=${AWS_REGION:-us-east-1}
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${ECR_URL%/*}"
cd ../backend && docker buildx build --platform linux/amd64 -t "$ECR_URL:latest" --load .
docker push "$ECR_URL:latest"

# 4. Seed RDS via SSM port-forward
cd ../infra
SUT=$(terraform output -raw sut_instance_id)
RDS=$(terraform output -raw rds_address)
aws ssm start-session --target "$SUT" --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$RDS\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"15432\"]}" &
sleep 5
DB_PASSWORD=$(grep '^db_password' terraform.tfvars | sed -E 's/.*= *"(.*)"/\1/')
SEED_DATABASE_URL="postgresql://opensre:${DB_PASSWORD}@localhost:15432/opensre_demo" \
  uv run ../scripts/seed_posts.py
kill %1

# 5. Scale ECS to 1 and deploy the UI
sed -i.bak 's/sut_desired_count = 0/sut_desired_count = 1/' terraform.tfvars
terraform apply -auto-approve
cd .. && ./scripts/deploy_ui.sh
```

Open the printed UI URL.

## Plan 2 quick start (OpenSRE host)

Builds on Plan 1. Stands up the agent EC2 that runs `opensre investigate` and posts RCAs to a Telegram group (where the downstream OpenClaw bot picks them up).

```bash
# 0. Prereqs (in addition to Plan 1):
#    - Anthropic API key
#    - Telegram bot from @BotFather (capture token)
#    - Telegram group with: OpenSRE bot + OpenClaw bot (capture chat ID like -1001234567890)
#    - session-manager-plugin, uuidgen
#    Set opensre_telegram_chat_id in infra/terraform.tfvars before applying.

# 1. First apply — secrets shells only (opensre_host_enabled defaults to false).
cd infra && terraform apply

# 2. Populate the two Secrets Manager values.
ANTHROPIC_SECRET=$(terraform output -raw anthropic_secret_id)
TELEGRAM_SECRET=$(terraform output -raw telegram_secret_id)
read -rs -p "Anthropic API key: " AK && echo
aws secretsmanager put-secret-value --secret-id "$ANTHROPIC_SECRET" --secret-string "$AK" && unset AK
read -rs -p "Telegram bot token: " TT && echo
aws secretsmanager put-secret-value --secret-id "$TELEGRAM_SECRET" --secret-string "$TT" && unset TT

# 3. Flip the toggle and re-apply — creates the EC2 + runs user-data + posts a Telegram "hello".
sed -i.bak 's/opensre_host_enabled = false/opensre_host_enabled = true/' terraform.tfvars
rm -f terraform.tfvars.bak
terraform apply

# 4. Wait for SSM to register the instance, then verify bootstrap completed.
HOST=$(terraform output -raw opensre_host_instance_id)
REGION=$(terraform output -raw aws_region)
for i in $(seq 1 24); do
  S=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$HOST" \
        --region "$REGION" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo Pending)
  echo "[$i] PingStatus: $S"; [ "$S" = "Online" ] && break; sleep 5
done
# Check Telegram for the "[OpenSRE bootstrap] host i-... online ..." message.

# 5. End-to-end smoke test: synthetic CPU alert → real RCA in the Telegram group (consumed by OpenClaw).
cd .. && ./scripts/test_opensre_alert.sh
```

If the smoke test produces an RCA in the Telegram group (and OpenClaw acknowledges it downstream), Plan 2 is complete.

## Teardown

```bash
cd infra && terraform destroy
```
