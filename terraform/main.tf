# Local-first by default. Set enable_aws=true (and provide AWS creds) for EC2.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # When AWS is disabled, use placeholder creds so plan/apply stay local-only.
  access_key = var.enable_aws ? null : "local-only"
  secret_key = var.enable_aws ? null : "local-only"

  skip_credentials_validation = !var.enable_aws
  skip_requesting_account_id  = !var.enable_aws
  skip_metadata_api_check     = true
  skip_region_validation      = !var.enable_aws
}

# Keeps a valid plan when AWS resources are gated off.
resource "null_resource" "local_ready" {
  count = var.enable_aws ? 0 : 1

  triggers = {
    note = "Local smoke path is active; set enable_aws=true to provision EC2."
  }
}

data "aws_ami" "amazon_linux" {
  count       = var.enable_aws ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_security_group" "mesen" {
  count       = var.enable_aws ? 1 : 0
  name        = "${var.name_prefix}-mesen"
  # AWS SG description is immutable; changing it forces replace while the
  # instance still holds the SG and wedges apply. Keep the original string.
  description = "SSH (and optional VNC) for remote Mesen host"

  # TCP 5900/5901 are intentionally absent. TigerVNC listens on 127.0.0.1:5901.
  # Reach it with: ssh -L 5901:127.0.0.1:5901 ec2-user@HOST
  # then: vnc://127.0.0.1:5901
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_ingress_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.name_prefix}-mesen"
    Project = "nes-keyboard"
  }

  # enable_vnc remains for existing tfvars. It must not add 5901 ingress.
  lifecycle {
    precondition {
      condition     = var.enable_vnc == true || var.enable_vnc == false
      error_message = "enable_vnc is ignored and must be a bool. VNC stays on 127.0.0.1 via an SSH tunnel."
    }
  }
}

resource "aws_instance" "mesen" {
  count                  = var.enable_aws ? 1 : 0
  ami                    = data.aws_ami.amazon_linux[0].id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.mesen[0].id]

  root_block_device {
    # Desktop stack + MesenCE zip + native deps need more than 8 GB.
    volume_size = 20
    volume_type = "gp3"
  }

  tags = {
    Name    = "${var.name_prefix}-mesen"
    Project = "nes-keyboard"
  }
}
