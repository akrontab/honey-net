variable "label" {
  description = "Instance name (used as Name tag and key pair name)"
  type        = string
}

variable "region" {
  description = "AWS region (e.g. us-east-1, eu-west-1, ap-southeast-1)"
  type        = string
}

variable "type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "ssh_pubkey" {
  description = "SSH public key content to authorize on the instance"
  type        = string
}

variable "root_pass" {
  description = "Unused — AWS uses SSH key pairs for access. Kept for interface parity."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied as EC2 resource tags (each tag becomes a key with empty value)"
  type        = list(string)
  default     = []
}
