variable "aws_profile" {
  description = "AWS CLI profile to use."
  type        = string
  default     = null
}

variable "region" {
  description = "AWS region. us-east-1 default per spec §8."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project tag and resource-name prefix."
  type        = string
  default     = "opensre-demo"
}

variable "db_password" {
  description = "RDS master password. Provide via TF_VAR_db_password or terraform.tfvars."
  type        = string
  sensitive   = true
}

variable "sut_ingress_cidr" {
  description = "CIDR allowed to hit the SUT EC2 on port 8080. Default 0.0.0.0/0 for demo; tighten to operator IP for safety."
  type        = string
  default     = "0.0.0.0/0"
}

variable "ui_bucket_suffix" {
  description = "Random suffix appended to the UI bucket name to avoid global collisions."
  type        = string
}

variable "sut_desired_count" {
  description = "ECS service desired count. Set to 0 for the first apply (no image yet); flip to 1 once the image is pushed."
  type        = number
  default     = 0
}
