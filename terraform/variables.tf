variable "linode_token" {
  description = "Linode API personal access token (Read/Write Linodes)"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "Linode region for all hosts (e.g. us-east, eu-west, ap-south)"
  type        = string
  default     = "us-east"
}
