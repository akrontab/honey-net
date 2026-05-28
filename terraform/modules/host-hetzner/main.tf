terraform {
  required_providers {
    hcloud = {
      source = "hetznercloud/hcloud"
    }
  }
}

resource "hcloud_ssh_key" "this" {
  name       = var.label
  public_key = trimspace(var.ssh_pubkey)
}

resource "hcloud_server" "this" {
  name        = var.label
  image       = "ubuntu-24.04"
  server_type = var.type
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.this.id]
  labels      = { for t in var.tags : t => "" }
}
