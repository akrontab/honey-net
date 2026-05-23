terraform {
  required_providers {
    linode = {
      source  = "linode/linode"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "linode" {
  token = var.linode_token
}

locals {
  servers = { for s in jsondecode(file("${path.module}/../honey-net.json")) : s.name => s }
}

resource "random_password" "root" {
  for_each = local.servers
  length   = 24
  special  = false
}

module "host" {
  for_each   = local.servers
  source     = "./modules/host"
  label      = each.key
  region     = var.region
  ssh_pubkey = file(pathexpand("${each.value.ssh_key}.pub"))
  root_pass  = random_password.root[each.key].result
  tags       = ["honey-net", each.value.type]
}
