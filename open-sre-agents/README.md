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

## Teardown

```bash
cd infra && terraform destroy
```
