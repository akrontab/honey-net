variable "label" {
  description = "Server name"
  type        = string
}

variable "location" {
  description = "Hetzner location (nbg1=Nuremberg, fsn1=Falkenstein, hel1=Helsinki, ash=Ashburn, hil=Hillsboro)"
  type        = string
}

variable "type" {
  description = "Hetzner server type (e.g. cx22)"
  type        = string
  default     = "cx22"
}

variable "ssh_pubkey" {
  description = "SSH public key content to authorize on the instance"
  type        = string
}

variable "root_pass" {
  description = "Unused — Hetzner uses SSH keys for access. Kept for interface parity with host-linode."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied as Hetzner labels (each tag becomes label key with empty value)"
  type        = list(string)
  default     = []
}
