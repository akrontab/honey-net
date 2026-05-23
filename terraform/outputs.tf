output "server_ips" {
  description = "Public IP addresses keyed by server name"
  value       = { for name, mod in module.host : name => mod.ip_address }
}

output "root_passwords" {
  description = "Generated root passwords for LISH console access (emergency only)"
  value       = { for name, pw in random_password.root : name => pw.result }
  sensitive   = true
}
