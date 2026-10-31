variable "aws_region" {
  type        = string
  description = "AWS region to deploy resources into."
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Deployment environment name (e.g. staging, production)."
  default     = "production"
}

variable "app_name" {
  type        = string
  description = "Application name prefix used across AWS resources."
  default     = "opsmind"
}

variable "instance_type" {
  type        = string
  description = "EC2 instance size for the OpsMind host (t4g.small or t3.micro for low cost)."
  default     = "t4g.small"
}

variable "ssh_public_key" {
  type        = string
  description = "Optional SSH public key for operator debugging access to the EC2 host."
  default     = ""
}

variable "app_allowed_cidr_blocks" {
  type        = list(string)
  description = "IPv4 CIDR blocks permitted to reach the OpsMind API and dashboard port."
  default     = ["0.0.0.0/0"]
}

# Deliberately has no default. SSH was previously open to the world because it
# shared the permissive app-port variable, so an apply must now name its source
# networks explicitly.
variable "ssh_allowed_cidr_blocks" {
  type        = list(string)
  description = "IPv4 CIDR blocks permitted to reach SSH. Set to your own address, never 0.0.0.0/0."

  validation {
    condition     = !contains(var.ssh_allowed_cidr_blocks, "0.0.0.0/0")
    error_message = "ssh_allowed_cidr_blocks must not be 0.0.0.0/0. Use SSM Session Manager instead."
  }
}

variable "app_port" {
  type        = number
  description = "TCP port the OpsMind API and dashboard listen on."
  default     = 8000
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention period in days to avoid unbounded storage costs."
  default     = 14
}

variable "enable_bedrock" {
  type        = bool
  description = "Whether to attach Amazon Bedrock invocation permissions to the IAM instance role."
  default     = true
}
