terraform {
  required_providers {
    linode = {
      source = "linode/linode"
    }
  }
}

resource "linode_instance" "this" {
  label           = var.label
  image           = "linode/ubuntu24.04"
  region          = var.region
  type            = var.type
  authorized_keys = [trimspace(var.ssh_pubkey)]
  root_pass       = var.root_pass
  tags            = var.tags
}
