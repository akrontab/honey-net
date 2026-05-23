output "ip_address" {
  description = "Public IPv4 address of the instance"
  value       = tolist(linode_instance.this.ipv4)[0]
}

output "label" {
  description = "Instance label"
  value       = linode_instance.this.label
}
