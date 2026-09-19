# AWS Cloud Deployment Guide

This guide walks through deploying OpsMind to AWS using Terraform and Amazon Bedrock.

---

## 1. Prerequisites

- [AWS CLI](https://aws.amazon.com/cli/) installed and configured (`aws configure`).
- [Terraform](https://www.terraform.io/) >= 1.5.0 installed.
- Access to Amazon Bedrock Anthropic Claude foundation models in your AWS Region (e.g., `us-east-1`).

---

## 2. Terraform Deployment in 3 Steps

### Step 1: Navigate to Terraform Directory

```bash
cd infra/terraform
```

### Step 2: Configure Variables

Copy the sample variables file:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` if you want to customize the region or instance type:
```hcl
aws_region     = "us-east-1"
environment    = "production"
app_name       = "opsmind"
instance_type  = "t4g.small"
enable_bedrock = true
```

### Step 3: Initialize and Apply

```bash
terraform init
terraform plan
terraform apply -auto-approve
```

Terraform will automatically provision:
- EC2 Instance with Docker
- SQS Queue + DLQ
- DynamoDB Table
- Encrypted S3 Artifacts Bucket
- EventBridge Bus & Rules
- CloudWatch Alarms & Log Groups
- Least-Privilege IAM Instance Profile

---

## 3. Post-Deployment Verification

Check the Terraform outputs:

```bash
terraform output
```

Output example:
```
api_endpoint        = "http://54.123.45.67:8000"
dynamodb_table_name = "opsmind-production-incidents"
s3_bucket_name      = "opsmind-production-artifacts-abc123"
sqs_queue_url       = "https://sqs.us-east-1.amazonaws.com/123456789012/opsmind-production-incidents-queue"
```

Verify the live API endpoint:
```bash
curl http://54.123.45.67:8000/healthz
# {"status":"ok","app":"OpsMind","mode":"aws"}
```

---

## 4. Teardown / Destruction

When you want to remove all provisioned AWS resources to avoid any ongoing costs:

```bash
cd infra/terraform
terraform destroy -auto-approve
```
