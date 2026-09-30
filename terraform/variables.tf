variable "enable_aws" {
  description = "When true, provision an EC2 host for remote Mesen. Keep false for local-only."
  type        = bool
  default     = false
}

variable "aws_region" {
  description = "AWS region for the Mesen host."
  type        = string
  default     = "us-east-2"
}

variable "name_prefix" {
  description = "Name prefix for AWS resources."
  type        = string
  default     = "nes-keyboard"
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Existing EC2 key pair name (required when enable_aws=true)."
  type        = string
  default     = ""
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to SSH to the Mesen host. VNC is not exposed; tunnel it over this SSH session."
  type        = string
  default     = "0.0.0.0/0"
}

variable "enable_vnc" {
  description = "Ignored. Kept so existing terraform.tfvars still apply. TigerVNC listens on 127.0.0.1:5901 and this setting does not add security-group ingress. Connect with ssh -L 5901:127.0.0.1:5901, then vnc://127.0.0.1:5901."
  type        = bool
  default     = false
}
