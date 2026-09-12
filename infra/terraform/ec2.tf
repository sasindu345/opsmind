# Lookup latest Ubuntu 24.04 LTS AMI
data "aws_ami" "ubuntu_arm64" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Default VPC and Subnets (No costly NAT Gateway required)
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "opsmind_sg" {
  name        = "${local.name_prefix}-sg"
  description = "Security group for OpsMind API and worker node"
  vpc_id      = data.aws_vpc.default.id

  # Port 8000 for OpsMind REST API and Webhooks
  ingress {
    description = "OpsMind REST API & Webhook Ingestion"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  # Port 22 for optional SSH
  ingress {
    description = "SSH Administration"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  # Outbound egress
  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-sg"
  }
}

resource "aws_key_pair" "opsmind_ssh_key" {
  count      = var.ssh_public_key != "" ? 1 : 0
  key_name   = "${local.name_prefix}-key"
  public_key = var.ssh_public_key
}

resource "aws_instance" "opsmind_host" {
  ami                  = data.aws_ami.ubuntu_arm64.id
  instance_type        = var.instance_type
  subnet_id            = data.aws_subnets.default.ids[0]
  iam_instance_profile = aws_iam_instance_profile.opsmind_profile.name
  key_name             = var.ssh_public_key != "" ? aws_key_pair.opsmind_ssh_key[0].key_name : null

  vpc_security_group_ids = [aws_security_group.opsmind_sg.id]

  associate_public_ip_address = true

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = <<-EOF
              #!/bin/bash
              set -ex
              exec > /var/log/opsmind-startup.log 2>&1
              export DEBIAN_FRONTEND=noninteractive

              apt-get update -y
              apt-get install -y ca-certificates curl git python3-pip python3-venv

              # Prepare app directory
              rm -rf /opt/opsmind
              git clone -b dev https://github.com/sasindu345/opsmind.git /opt/opsmind
              cd /opt/opsmind

              # Setup Python virtual environment & dependencies
              python3 -m venv /opt/opsmind/.venv
              /opt/opsmind/.venv/bin/pip install --upgrade pip
              /opt/opsmind/.venv/bin/pip install -r /opt/opsmind/requirements.txt

              # Write production environment configuration
              cat << 'ENVFILE' > /opt/opsmind/.env
              DEPLOYMENT_MODE=aws
              AWS_REGION=${var.aws_region}
              SQS_QUEUE_URL=${aws_sqs_queue.incidents_queue.url}
              SQS_DLQ_URL=${aws_sqs_queue.incidents_dlq.url}
              DYNAMODB_TABLE_NAME=${aws_dynamodb_table.incidents.name}
              S3_BUCKET_NAME=${aws_s3_bucket.artifacts.bucket}
              EVENTBRIDGE_BUS_NAME=${aws_cloudwatch_event_bus.opsmind_bus.name}
              LLM_PROVIDER=bedrock
              BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
              APP_ENV=production
              LOG_LEVEL=INFO
              REPORTS_DIR=/opt/opsmind/reports
              ENVFILE

              mkdir -p /opt/opsmind/reports /opt/opsmind/data /opt/opsmind/artifacts
              chown -R ubuntu:ubuntu /opt/opsmind

              # 1. Create OpsMind Web API Systemd Service
              cat << 'SERVICE' > /etc/systemd/system/opsmind.service
              [Unit]
              Description=OpsMind AIOps Web Platform & API
              After=network.target

              [Service]
              Type=simple
              User=ubuntu
              WorkingDirectory=/opt/opsmind
              EnvironmentFile=/opt/opsmind/.env
              ExecStart=/opt/opsmind/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
              Restart=always
              RestartSec=3

              [Install]
              WantedBy=multi-user.target
              SERVICE

              # 2. Create OpsMind Queue Worker Systemd Service
              cat << 'WORKER' > /etc/systemd/system/opsmind-worker.service
              [Unit]
              Description=OpsMind Async SQS Incident Worker
              After=network.target

              [Service]
              Type=simple
              User=ubuntu
              WorkingDirectory=/opt/opsmind
              EnvironmentFile=/opt/opsmind/.env
              ExecStart=/opt/opsmind/.venv/bin/python -m src.cli.opsmind_cli worker --interval 0.5
              Restart=always
              RestartSec=3

              [Install]
              WantedBy=multi-user.target
              WORKER

              # Enable & start both services
              systemctl daemon-reload
              systemctl enable --now opsmind.service
              systemctl enable --now opsmind-worker.service
              EOF

  tags = {
    Name = "${local.name_prefix}-host"
  }
}
