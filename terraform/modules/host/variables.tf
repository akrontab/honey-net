variable "label" {
  description = "Linode instance label"
  type        = string
}

variable "region" {
  description = "Linode region"
  type        = string
}

variable "type" {
  description = "Linode instance type"
  type        = string
  default     = "g6-nanode-1"
}

variable "ssh_pubkey" {
  description = "SSH public key content to authorize on the instance"
  type        = string
}

variable "root_pass" {
  description = "Root password for emergency LISH console access"
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags to apply to the instance"
  type        = list(string)
  default     = []
}
