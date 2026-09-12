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

  user_data_replace_on_change = true
  depends_on                  = [aws_s3_object.app_package]

  user_data = templatefile("${path.module}/scripts/bootstrap.sh.tftpl", {
    aws_region           = var.aws_region
    s3_bucket_name       = aws_s3_bucket.artifacts.bucket
    sqs_queue_url        = aws_sqs_queue.incidents_queue.url
    sqs_dlq_url          = aws_sqs_queue.incidents_dlq.url
    dynamodb_table_name  = aws_dynamodb_table.incidents.name
    eventbridge_bus_name = aws_cloudwatch_event_bus.opsmind_bus.name
  })

  tags = {
    Name = "${local.name_prefix}-host"
  }
}
