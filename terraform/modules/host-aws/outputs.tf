output "ip_address" {
  description = "Public IPv4 address of the instance"
  value       = aws_instance.this.public_ip
}

output "label" {
  description = "Instance name"
  value       = aws_instance.this.tags["Name"]
}
