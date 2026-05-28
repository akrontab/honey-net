output "ip_address" {
  description = "Public IPv4 address of the instance"
  value       = hcloud_server.this.ipv4_address
}

output "label" {
  description = "Server name"
  value       = hcloud_server.this.name
}
