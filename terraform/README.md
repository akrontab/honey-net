# terraform

Manages all honey-net cloud infrastructure on Linode. Each host is a Nanode (1 vCPU, 1GB RAM, $5/mo) running Ubuntu 24.04 LTS.

Servers are driven by `honey-net.json` at the repo root — adding a server entry there is the only change needed before `terraform apply`. No edits to any `.tf` file required.

## Prerequisites

- **Terraform** — [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install)
- **Linode API token** — cloud.linode.com → Profile → API Tokens → Create. Required scopes: Linodes (Read/Write), Events (Read Only).
- **SSH key pairs** — one per server, paths set in `honey-net.json`:
  ```powershell
  ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\log-stack-linode"
  ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\mysql-ssh-honeypot"
  ```

## Setup

```powershell
copy terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — add linode_token (and optionally region)
terraform init
```

## Usage

```powershell
terraform plan      # preview changes
terraform apply     # create / update infrastructure
terraform destroy   # tear down all hosts
```

After `apply`, run from the honey-net root to capture IPs:
```
python sync_ips.py
```

## Adding a server

1. Add an entry to `honey-net.json` (name, type, ssh_key, honeypots, ports).
2. Generate an SSH key pair matching the `ssh_key` path.
3. `terraform apply` — the new VM is created automatically via `for_each`.
4. `python sync_ips.py` — adds the new server to `state.json`.

## Retrieving root passwords

Root passwords are auto-generated and stored in Terraform state. Needed only for emergency LISH console access (normal access uses SSH keys over Tailscale):

```powershell
terraform output -json root_passwords
```

## Layout

```
main.tf                    # provider config + for_each over honey-net.json
variables.tf               # linode_token and region
outputs.tf                 # server_ips and root_passwords
terraform.tfvars.example   # copy to terraform.tfvars and fill in secrets
modules/
  host/                    # reusable module — one Linode Nanode instance
```

## Notes

- **Renaming a server** in `honey-net.json` destroys and recreates it (resources are keyed by name). Fine for honeypots; use `terraform state mv` first for backends like log-stack.
- **State file** (`terraform.tfstate`) is local and gitignored. For multi-machine workflows, configure a remote backend (S3, Terraform Cloud) in `main.tf`.
- **Secrets** — `terraform.tfvars` and `*.tfstate` are gitignored. Never commit them.
