output "mode" {
  description = "local or aws depending on enable_aws"
  value       = var.enable_aws ? "aws" : "local"
}

output "instance_id" {
  description = "EC2 instance id when AWS is enabled"
  value       = try(aws_instance.mesen[0].id, null)
}

output "public_ip" {
  description = "EC2 public IP for Ansible inventory when AWS is enabled"
  value       = try(aws_instance.mesen[0].public_ip, null)
}

output "ssh_host" {
  description = "Convenience SSH target when AWS is enabled"
  value       = try(aws_instance.mesen[0].public_ip, null)
}

output "vnc_url" {
  description = "VNC client URL. Open this only after ssh -L 5901:127.0.0.1:5901 to the instance. The security group does not allow TCP 5901. enable_vnc does not change that."
  value       = var.enable_aws ? "vnc://127.0.0.1:5901" : null
}
