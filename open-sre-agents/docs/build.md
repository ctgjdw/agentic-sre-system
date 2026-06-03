# How the Build Script Works

This document explains what `scripts/build.sh` does, step by step. It includes a beginner-friendly introduction to Terraform, since the build script leans heavily on it.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Terraform Primer](#terraform-primer)
  - [What is Terraform?](#what-is-terraform)
  - [Key Concepts](#key-concepts)
  - [How This Project Uses Terraform](#how-this-project-uses-terraform)
  - [The Two-Phase Apply Pattern](#the-two-phase-apply-pattern)
- [Build Phases in Detail](#build-phases-in-detail)
  - [Phase 0: Prerequisite Checks](#phase-0-prerequisite-checks)
  - [Phase 1: terraform.tfvars Bootstrap](#phase-1-terraformtfvars-bootstrap)
  - [Phase B: Cold Terraform Apply](#phase-b-cold-terraform-apply)
  - [Phase C1: Build and Push Backend Image](#phase-c1-build-and-push-backend-image)
  - [Phase C2-C3: Seed the Database](#phase-c2-c3-seed-the-database)
  - [Phase D: Populate Secrets Manager](#phase-d-populate-secrets-manager)
  - [Phase E: Hot Terraform Apply](#phase-e-hot-terraform-apply)
  - [Phase F: Deploy UI](#phase-f-deploy-ui)
- [What Gets Created in AWS](#what-gets-created-in-aws)
- [Re-running the Script (Idempotency)](#re-running-the-script-idempotency)
- [Verification Gates](#verification-gates)
- [Tearing Down](#tearing-down)

---

## Prerequisites

The script checks for all of these at startup and will exit with a helpful error if any are missing:

| Tool | Purpose |
|------|---------|
| `aws` (AWS CLI v2) | Interact with AWS services |
| `terraform` (1.9+) | Provision infrastructure |
| `docker` (with buildx) | Build the backend container image |
| `uv` | Run the Python database seeding script |
| `node` (20+) / `npm` | Build the Next.js frontend |
| `jq` | Parse JSON from AWS API responses |
| `session-manager-plugin` | SSM port-forwarding to reach the private RDS database |
| `python3` (3.6+) | Generate random values for config bootstrapping |

You also need valid AWS credentials (`AWS_PROFILE` or `aws configure`).

## Quick Start

```bash
# First run: creates terraform.tfvars, prints instructions, then exits.
./scripts/build.sh

# Edit the generated file:
vi infra/terraform.tfvars

# Second run: builds everything.
./scripts/build.sh
```

---

## Terraform Primer

### What is Terraform?

Terraform is an **Infrastructure as Code (IaC)** tool. Instead of clicking through the AWS Console to create a VPC, a database, an EC2 instance, etc., you write `.tf` files that **declare** what you want to exist. Terraform reads those files, compares them to what currently exists in AWS, and creates/updates/deletes resources to make reality match your declaration.

Think of it like this:

```
You write:  "I want a VPC, a database, and an EC2 instance."
Terraform:  "OK. The VPC already exists. The database needs a password change. The EC2 instance is new."
             → updates the database password
             → creates the EC2 instance
             → leaves the VPC alone
```

This is called **declarative** infrastructure: you say *what* you want, not *how* to get there.

### Key Concepts

#### Files and Directory Structure

All Terraform files live in `infra/`. Terraform treats **every `.tf` file in the same directory** as a single configuration. The filenames are just for human organisation -- Terraform merges them all together. Our project splits them by concern:

| File | What it defines |
|------|-----------------|
| `versions.tf` | Which Terraform version and provider versions we need |
| `providers.tf` | Configures the AWS provider (region, default tags) |
| `variables.tf` | Input variables (region, passwords, feature flags) |
| `network.tf` | VPC, subnets, route tables, security groups |
| `rds.tf` | The PostgreSQL database |
| `ecr.tf` | Docker image registry (ECR) |
| `ecs.tf` | ECS cluster + SUT EC2 host that runs the backend container |
| `ecs_service.tf` | ECS service + task definition for the backend app |
| `s3.tf` | S3 bucket for the frontend UI (static website hosting) |
| `secrets.tf` | AWS Secrets Manager entries (Anthropic API key, Telegram token) |
| `opensre_host.tf` | The OpenSRE agent EC2 instance (separate from SUT) |
| `lambda.tf` | Lambda function that ingests CloudWatch alarms |
| `alarms.tf` | CloudWatch alarms + SNS topic |
| `fis.tf` | AWS Fault Injection Service experiment templates |
| `ssm_logs.tf` | CloudWatch log group for SSM command output |
| `outputs.tf` | Values Terraform prints after apply (URLs, IDs, etc.) |

#### `terraform init`

The first command you run. Downloads the **provider plugins** (the AWS plugin that knows how to talk to AWS APIs). Also sets up the **state backend** (where Terraform stores what it has created). This project uses a local state file (`terraform.tfstate` in the `infra/` directory).

```bash
cd infra
terraform init
```

You only need to re-run this when provider versions change (or when the `.terraform/` cache is stale -- which is what happened during our first build attempt).

#### `terraform apply`

The main command. Terraform:

1. **Reads** all `.tf` files to build a desired state.
2. **Reads** the state file (`terraform.tfstate`) to see what already exists.
3. **Computes a plan** -- a diff showing what it will create, update, or destroy.
4. **Executes the plan** -- makes the AWS API calls.

The `-auto-approve` flag skips the interactive "Do you want to apply?" prompt. The `-input=false` flag prevents Terraform from prompting for missing variables (it will error instead).

#### Variables (`var.something`)

Defined in `variables.tf`, values come from `terraform.tfvars`:

```hcl
# variables.tf -- the declaration (type, description, optional default)
variable "db_password" {
  type      = string
  sensitive = true              # Terraform won't print this in logs
}

# terraform.tfvars -- the actual value
db_password = "s0me_Rand0m_Pa55"
```

Variables can also be set on the command line with `-var`:

```bash
terraform apply -var "sut_desired_count=0"
```

Command-line `-var` overrides the value in `terraform.tfvars`.

#### Resources

The building blocks. Each `resource` block tells Terraform to create one AWS thing:

```hcl
resource "aws_vpc" "main" {       # type = "aws_vpc", name = "main"
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  tags = { Name = "opensre-demo-vpc" }
}
```

- `"aws_vpc"` -- the resource type. `aws_` means the AWS provider handles it; `vpc` is the specific service.
- `"main"` -- a local name you pick. Other resources refer to this one as `aws_vpc.main`.
- Inside the block are the resource's configuration arguments.

#### Resource References

Resources can reference each other. Terraform uses these references to figure out the **dependency order** (what to create first):

```hcl
resource "aws_subnet" "public_a" {
  vpc_id = aws_vpc.main.id        # ← "create the VPC first, then use its ID here"
  # ...
}
```

You never have to say "create the VPC before the subnet." Terraform infers it from the reference.

#### `count` (Conditional Resources)

A resource with `count = 0` is not created at all. This project uses this pattern to gate resources on a boolean variable:

```hcl
resource "aws_instance" "opensre" {
  count = var.opensre_host_enabled ? 1 : 0    # create 1 if true, 0 if false
  # ...
}
```

When `count` is used, you refer to the resource as a list: `aws_instance.opensre[0]`. If `count = 0`, that list is empty and `[0]` would be an error -- that's why other resources that depend on the OpenSRE host also need to be gated with the same `count`.

#### Outputs

Values Terraform prints after a successful apply. Other scripts read them:

```hcl
output "sut_api_url" {
  value = "http://${aws_eip.sut.public_ip}:8080"
}
```

The build script reads outputs with:

```bash
terraform output -raw sut_api_url
# prints: http://18.123.45.67:8080
```

#### State

Terraform stores everything it created in a **state file** (`terraform.tfstate`). This is how it knows what already exists. If you delete the state file, Terraform thinks nothing exists and will try to create everything again (resulting in conflicts with the real resources). **Never delete the state file** unless you're intentionally starting from scratch and have destroyed the real resources.

### How This Project Uses Terraform

All 56 AWS resources are defined across the `.tf` files in `infra/`. Here's the architecture in plain English:

```
                    ┌─────────────────────────────────────┐
                    │            VPC (10.20.0.0/16)       │
                    │                                     │
                    │  ┌──────────────┐ ┌──────────────┐  │
                    │  │ Public Sub A │ │ Public Sub B │  │
                    │  │              │ │              │  │
                    │  │  SUT EC2     │ │              │  │
                    │  │  (ECS host)  │ │              │  │
                    │  │              │ │              │  │
                    │  │  OpenSRE EC2 │ │              │  │
                    │  │  (agent)     │ │              │  │
                    │  └──────────────┘ └──────────────┘  │
                    │                                     │
                    │  ┌──────────────┐ ┌──────────────┐  │
                    │  │ Private Sub A│ │ Private Sub B│  │
                    │  │   RDS (PG)   │ │              │  │
                    │  └──────────────┘ └──────────────┘  │
                    └─────────────────────────────────────┘

  S3 Bucket (UI)       ECR (backend image)      Secrets Manager
  CloudWatch Alarms    SNS Topic                 Lambda (ingest)
  FIS Experiment       CloudWatch Log Groups
  Templates
```

- **SUT (System Under Test)**: An EC2 instance running ECS, which hosts a Docker container with the backend API. This is the app being monitored.
- **OpenSRE Host**: A separate EC2 instance running the OpenSRE agent. Kept separate so that chaos experiments targeting the SUT don't crash the agent.
- **RDS**: A PostgreSQL database in private subnets (not reachable from the internet).
- **S3**: Hosts the static frontend (Next.js export).

### The Two-Phase Apply Pattern

This is the most important thing to understand about the build script. Terraform is run **twice**:

**Cold apply** (`sut_desired_count=0`, `opensre_host_enabled=false`):
- Creates the VPC, subnets, security groups, RDS, ECR, S3 bucket, Secrets Manager shells, ECS cluster, SUT EC2 host, CloudWatch alarms, SNS topic, and FIS templates.
- Does **not** start the backend container (no image in ECR yet).
- Does **not** create the OpenSRE EC2 host (secrets aren't populated yet).

**Hot apply** (`sut_desired_count=1`, `opensre_host_enabled=true`):
- Creates the OpenSRE EC2 host (secrets are now populated).
- Creates the Lambda function and wires it to SNS.
- Sets ECS desired count to 1, which starts the backend container.

Why two phases? A chicken-and-egg problem:
1. The backend Docker image needs ECR to exist before it can be pushed.
2. The OpenSRE host's bootstrap script reads secrets from Secrets Manager on first boot, so those secrets must be populated before the EC2 instance is created.
3. The ECS service can't start a task if no image exists in ECR.

Splitting into two applies solves all three: create the infrastructure shells first, fill them (push image, populate secrets, seed database), then bring everything online.

---

## Build Phases in Detail

### Phase 0: Prerequisite Checks

**Script lines 70-106** -- Verifies all required CLI tools are installed. Confirms AWS credentials work by calling `aws sts get-caller-identity`. Prints the AWS account ID.

If anything is missing, the script exits immediately with an installation link.

### Phase 1: terraform.tfvars Bootstrap

**Script lines 108-153** -- On the very first run, `infra/terraform.tfvars` won't exist. The script:

1. Copies `terraform.tfvars.example` to `terraform.tfvars`.
2. Generates a random 24-character database password and an 8-character hex bucket suffix using Python's `secrets` module.
3. Writes these into the new file.
4. Prints instructions to edit the file (set your region, ingress CIDR, and Telegram chat ID).
5. **Exits** -- you must edit the file and re-run.

On subsequent runs, the script validates that example placeholders (`REPLACE_ME`, `-1001234567890`, `abc123def`) have been replaced.

### Phase B: Cold Terraform Apply

**Script lines 155-194** -- Runs `terraform init` (if `.terraform/` doesn't exist) then:

```bash
terraform apply -input=false -auto-approve \
  -var "sut_desired_count=0" \
  -var "opensre_host_enabled=false"
```

The `-var` flags **override** whatever is in `terraform.tfvars` for these two variables, ensuring we get a cold apply regardless of the file's contents.

After the apply, the script reads Terraform outputs to get:
- `REGION` -- the AWS region
- `ECR_URL` -- where to push Docker images
- `SUT_INSTANCE_ID` -- the EC2 instance ID (for SSM port-forwarding)
- `RDS_ADDRESS` -- the database hostname
- `ANTHROPIC_SECRET` / `TELEGRAM_SECRET` -- Secrets Manager IDs

It then waits up to 10 minutes for RDS to become available (RDS creation takes 5-10 minutes).

**What Terraform creates in this phase (56 resources):**

| Category | Resources |
|----------|-----------|
| Networking | VPC, 2 public subnets, 2 private subnets, internet gateway, 2 route tables, 4 route table associations, 3 security groups |
| Database | RDS instance (PostgreSQL 16, db.t3.micro), DB subnet group, parameter group |
| Compute | ECS cluster, SUT EC2 instance, EIP, EIP association, ECS task definition, ECS service (desired_count=0) |
| Container registry | ECR repository |
| Storage | S3 bucket, website config, public access block, bucket policy |
| Secrets | 2 Secrets Manager entries (empty shells) |
| Monitoring | 2 CloudWatch alarms, SNS topic, log metric filter, 2 log groups |
| Chaos | 2 FIS experiment templates |
| IAM | Multiple roles, policies, instance profiles |

### Phase C1: Build and Push Backend Image

**Script lines 198-230** -- Builds the backend Docker image and pushes it to ECR.

1. **Idempotency check**: If ECR already has an image tagged `:latest`, this step is skipped (saves time on re-runs).
2. Logs in to ECR using `aws ecr get-login-password`.
3. Builds a linux/amd64 image from `backend/` using `docker buildx`.
4. Pushes the image to ECR.

### Phase C2-C3: Seed the Database

**Script lines 232-289** -- The RDS instance is in a private subnet (no internet access, no direct connection from your machine). To seed it, the script uses **SSM port-forwarding** through the SUT EC2 instance:

```
Your machine:15432  ──SSM tunnel──>  SUT EC2  ──VPC network──>  RDS:5432
```

Step by step:
1. Starts an SSM port-forwarding session in the background, mapping `localhost:15432` to `RDS_ADDRESS:5432` through the SUT instance.
2. Sets a cleanup trap so the port-forward is killed on script exit.
3. Waits up to 30 seconds for the local port to accept connections (using a Python socket check -- works cross-platform).
4. Runs `scripts/seed_posts.py` via `uv run`, which connects to `localhost:15432` and inserts 10,000 rows.
5. Kills the port-forward and removes the exit trap.

### Phase D: Populate Secrets Manager

**Script lines 292-342** -- Checks each secret in AWS Secrets Manager. If empty (never set), prompts you to enter the value interactively:

- **Anthropic API key** (`sk-ant-...`): Used by the OpenSRE agent to call Claude.
- **Telegram bot token** (`123456:ABC...`): Used to post RCA reports to your Telegram group.

If the secrets already have values (e.g., from a previous run), this step is skipped. Input is read silently (characters aren't echoed to the terminal).

The values are stored **only** in AWS Secrets Manager -- they never touch the repo, Terraform state, or local files.

### Phase E: Hot Terraform Apply

**Script lines 344-411** -- The second `terraform apply`:

```bash
terraform apply -input=false -auto-approve \
  -var "sut_desired_count=1" \
  -var "opensre_host_enabled=true"
```

This time:
- `opensre_host_enabled=true` creates the OpenSRE EC2 instance. Its `user_data` bootstrap script installs the OpenSRE CLI, reads secrets from Secrets Manager, and sends a "host online" message to Telegram.
- `sut_desired_count=1` tells ECS to start one task, which pulls the Docker image from ECR and launches the backend API.
- The Lambda function, its IAM policy, SNS subscription, and SNS permission are also created (they reference the OpenSRE host's instance ID).

After the apply, the script:

1. Updates `terraform.tfvars` to set `sut_desired_count = 1` and `opensre_host_enabled = true`, so future manual `terraform apply` commands don't accidentally revert to the cold state.
2. Waits up to 3 minutes for the SUT's `/health` endpoint to return HTTP 200.
3. Waits up to 2 minutes for the OpenSRE host to register with SSM (status = "Online").

### Phase F: Deploy UI

**Script lines 413-419** -- Runs `scripts/deploy_ui.sh`, which:

1. Reads the SUT API URL and S3 bucket name from Terraform outputs.
2. Builds the Next.js frontend with `NEXT_PUBLIC_API_URL` pointed at the SUT.
3. Syncs the static export to the S3 bucket with `aws s3 sync --delete`.

---

## What Gets Created in AWS

After a successful build, you'll have:

| Resource | Purpose | Approx. cost (free tier) |
|----------|---------|--------------------------|
| VPC + subnets | Network isolation | Free |
| SUT EC2 (t3.micro) | Runs the backend API via ECS | 750 hrs/mo free |
| OpenSRE EC2 (t3.micro) | Runs the OpenSRE agent | 750 hrs/mo free (shared) |
| RDS (db.t3.micro, 20 GB) | PostgreSQL database | 750 hrs/mo free |
| ECR | Stores backend Docker image | 500 MB free |
| S3 | Hosts the frontend UI | 5 GB free |
| Lambda | Ingests CloudWatch alarms, triggers OpenSRE | 1M requests/mo free |
| CloudWatch | Logs + alarms | 5 GB ingestion free |
| Secrets Manager | API keys | $0.40/secret/month |
| FIS | Chaos experiment templates | Pay per experiment run |

## Re-running the Script (Idempotency)

The script is designed to be re-run safely after a partial failure:

- **terraform.tfvars** -- Only created on the very first run.
- **terraform init** -- Skipped if `.terraform/` already exists.
- **terraform apply** -- Terraform is inherently idempotent; it only changes what's different.
- **Docker push** -- Skipped if ECR already has a `:latest` tag.
- **Database seed** -- The seed script is idempotent (inserts are conditional).
- **Secrets** -- Skipped if already populated.
- **UI deploy** -- `aws s3 sync` only uploads changed files.

## Verification Gates

After the build, the script prints three verification gates:

- **G1** -- `./scripts/test_opensre_alert.sh`: Sends a synthetic alarm to test the Lambda -> OpenSRE -> Telegram pipeline.
- **G2** -- Manual CloudWatch alarm transition: Forces the CPU alarm into ALARM state to verify the SNS -> Lambda path.
- **G3** -- `./scripts/start_chaos.sh cpu` / `rds`: Runs actual FIS chaos experiments (the full MVP end-to-end test).

Use `--skip-verify` to suppress these instructions.

## Tearing Down

To destroy everything:

```bash
cd infra
terraform destroy -auto-approve
```

This removes all 56+ AWS resources. The S3 bucket and ECR repo have `force_destroy = true`, so they'll be deleted even if they contain objects/images.
