variable "label" {
  description = "Server name (used for all Azure resource names)"
  type        = string
}

variable "location" {
  description = "Azure location (e.g. eastus, westeurope, southeastasia)"
  type        = string
}

variable "type" {
  description = "Azure VM size"
  type        = string
  default     = "Standard_B1s"
}

variable "ssh_pubkey" {
  description = "SSH public key content to authorize on the instance"
  type        = string
}

variable "root_pass" {
  description = "Unused — Azure uses SSH keys for access. Kept for interface parity."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied as Azure resource tags (each tag becomes a key with empty value)"
  type        = list(string)
  default     = []
}
