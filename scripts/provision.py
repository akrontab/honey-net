#!/usr/bin/env python3
"""End-to-end provisioning for honey-net: terraform + server setup.

Phases:
  1. Terraform — creates VMs on Linode, writes public IPs to state.json
                 (skip with --skip-terraform if infrastructure already exists)
  2. Server setup — for each server in dependency order:
       a. Generate Tailscale auth key
       b. Assemble + SCP deploy package
       c. SSH + run setup.sh with env vars (no interactive prompts on the server)
       d. Poll Tailscale API until the node registers; write Tailscale IP to state.json
       e. Thread LOKI_HOST / CATALOG_URL forward to subsequent servers

Backends are provisioned before honeypots. Within backends, log-stack comes before
malware-catalog because honeypots need the log-stack Tailscale IP as LOKI_HOST.

Usage:
  python provision.py                         # terraform + provision all servers
  python provision.py --skip-terraform        # skip terraform, use existing state.json
  python provision.py --infra-only            # terraform + write state.json, then stop
  python provision.py --server NAME           # provision one server (terraform still runs
                                              # unless --skip-terraform is also given)
  python provision.py --skip-terraform --force  # reprovision even already-provisioned servers

Resilience behaviour:
  - Waits up to 120s for SSH to become available after VM creation before SCP.
  - Retries SCP up to 6× on transient failures.
  - Handles Tailscale API 429 rate-limiting in the post-setup poll loop.
  - Writes state.json atomically (temp file + rename) so Ctrl+C cannot corrupt it.
  - Skips servers that already have a tailscale_ip in state.json (prompts to confirm);
    use --force to reprovision without the prompt.
"""

import argparse
import getpass
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(1, str(Path(__file__).resolve().parent))  # for check_ssh_keys

from lib.color import bold, green, gray, yellow
from lib.config import REPO_ROOT, load_manifest
from lib.files import copy_tree
from lib.package import assemble_honeypot_package
from lib.ssh import DEVNULL, ssh_key, ssh_base_args, scp_args, run_ssh
from check_ssh_keys import check_or_create

_CONF_FILES = ["sshd_hardening.conf", "99-hardening.conf", "fail2ban-jail.local"]
_TF_DIR = REPO_ROOT / "terraform"
_STATE_FILE = REPO_ROOT / "state.json"

# ── Terraform phase ───────────────────────────────────────────────────────────

def _check_terraform():
    r = subprocess.run(["terraform", "version"], capture_output=True)
    if r.returncode != 0:
        sys.exit(
            "terraform not found in PATH.\n"
            "Install from https://developer.hashicorp.com/terraform/install"
        )


def _ensure_tfvars(linode_token):
    """Create terraform.tfvars from the provided token if it doesn't exist."""
    tfvars = _TF_DIR / "terraform.tfvars"
    if tfvars.exists():
        return
    region = input("Linode region [us-central]: ").strip() or "us-central"
    tfvars.write_text(
        f'linode_token = "{linode_token}"\nregion       = "{region}"\n',
        encoding="utf-8",
    )
    print(f"Created terraform/terraform.tfvars (region={region})")


def _terraform_init():
    if (_TF_DIR / ".terraform").exists():
        return
    print("\n[terraform] Initialising providers (first run)...")
    r = subprocess.run(["terraform", f"-chdir={_TF_DIR}", "init", "-input=false"])
    if r.returncode != 0:
        sys.exit("terraform init failed")


def _terraform_apply():
    print("\n[terraform] Applying infrastructure...")
    r = subprocess.run([
        "terraform", f"-chdir={_TF_DIR}",
        "apply", "-auto-approve", "-input=false",
    ])
    if r.returncode != 0:
        sys.exit("terraform apply failed")


def _write_state(state):
    """Atomically write state to state.json (safe against Ctrl+C mid-write)."""
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, _STATE_FILE)


def _terraform_write_state():
    """Read terraform outputs and write public IPs to state.json."""
    r = subprocess.run(
        ["terraform", f"-chdir={_TF_DIR}", "output", "-json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit(f"terraform output failed:\n{r.stderr.strip()}")

    outputs = json.loads(r.stdout)
    server_ips_block = outputs.get("server_ips")
    if server_ips_block is None:
        sys.exit(
            "terraform output missing 'server_ips' key — "
            "did 'terraform apply' complete successfully?"
        )
    public_ips = server_ips_block.get("value", {})
    if not public_ips:
        sys.exit("terraform output 'server_ips' is empty — no servers were created")

    # Preserve Tailscale IPs from any prior partial run
    state = {}
    if _STATE_FILE.exists():
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))

    for name, ip in public_ips.items():
        state.setdefault(name, {})["public_ip"] = ip

    _write_state(state)
    print(f"\n[terraform] state.json written — {len(public_ips)} server(s):")
    for name, ip in sorted(public_ips.items()):
        print(f"  {name:<25} {ip}")
    return state


def run_terraform(linode_token):
    _check_terraform()
    _ensure_tfvars(linode_token)
    _terraform_init()
    _terraform_apply()
    return _terraform_write_state()

# ── Tailscale helpers ─────────────────────────────────────────────────────────

def _load_ts_api_key():
    key_file = Path.home() / ".tailscale-apikey"
    if key_file.exists():
        return key_file.read_text().strip()
    print("No Tailscale API key found at ~/.tailscale-apikey")
    print("Generate one at: tailscale.com → Settings → Keys → Generate API key\n")
    key = getpass.getpass("Tailscale API key: ").strip()
    if not key:
        sys.exit("Tailscale API key is required.")
    answer = input(f"Save to {key_file} for future use? [y/N] ").strip().lower()
    if answer == "y":
        key_file.write_text(key)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        print("Saved.")
    return key


def _load_optional_key(label, key_file_name, url):
    """Prompt for an optional API key, reading from ~/.honey-net-<name> if saved.

    Returns the key string, or "" if the user skips.
    """
    key_file = Path.home() / key_file_name
    if key_file.exists():
        key = key_file.read_text().strip()
        if key:
            print(f"  {label}: loaded from ~/{key_file_name}")
            return key
    print(f"\n  {label} (optional — press Enter to skip)")
    print(f"  Get one at: {url}")
    key = getpass.getpass(f"  {label}: ").strip()
    if not key:
        print(f"  Skipping {label}.")
        return ""
    answer = input(f"  Save to ~/{key_file_name} for future use? [y/N] ").strip().lower()
    if answer == "y":
        key_file.write_text(key)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        print("  Saved.")
    return key


def _gen_ts_key(api_key, *, ephemeral=False):
    import requests
    body = {
        "capabilities": {
            "devices": {"create": {"reusable": False, "ephemeral": ephemeral,
                                   "preauthorized": False, "tags": []}}
        },
        "expirySeconds": 90 * 86400,
    }
    try:
        resp = requests.post(
            "https://api.tailscale.com/api/v2/tailnet/-/keys",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body, timeout=10,
        )
    except requests.RequestException as e:
        sys.exit(f"Tailscale API error: {e}")
    if resp.status_code == 401:
        (Path.home() / ".tailscale-apikey").unlink(missing_ok=True)
        sys.exit("Tailscale API key rejected (401). Generate a new one at tailscale.com.")
    resp.raise_for_status()
    return resp.json()["key"]


def _await_ssh(pub_ip, key, *, timeout=240, interval=10):
    """Block until SSH on port 22 accepts connections (VM boot wait)."""
    print(f"  Waiting for SSH on {pub_ip}", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = subprocess.run(
                ssh_base_args(key, 22, pub_ip) + ["exit"],
                capture_output=True,
                timeout=15,
            )
            if r.returncode == 0:
                print(" ready")
                return
        except subprocess.TimeoutExpired:
            pass  # connection established but slow — keep retrying
        print(".", end="", flush=True)
        time.sleep(interval)
    print()
    sys.exit(f"SSH not available on {pub_ip} after {timeout}s — VM may still be booting")


def _poll_tailscale_ip(api_key, hostname, *, timeout=300, interval=10):
    """Poll until hostname appears in the tailnet; return its 100.x IP or None."""
    import requests
    print(f"  Waiting for '{hostname}' in tailnet", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(
                "https://api.tailscale.com/api/v2/tailnet/-/devices",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 30))
                print(f"(rate limited, waiting {wait}s)", end="", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            for dev in resp.json().get("devices", []):
                if dev["hostname"] == hostname:
                    ip = next((a for a in dev.get("addresses", []) if a.startswith("100.")), None)
                    if ip:
                        print(f" → {green(ip)}")
                        return ip
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(interval)
    print()
    return None

# ── Package staging ───────────────────────────────────────────────────────────

def _stage_backend(server, pkg_dir):
    src = REPO_ROOT / server["name"] / "deploy"
    if not src.exists():
        sys.exit(f"Backend deploy folder not found: {src}")
    copy_tree(src, pkg_dir, exclude_names={".env"})


def _stage_honeypot(server, pkg_dir):
    pkg_dir.mkdir()
    assemble_honeypot_package(server, pkg_dir)
    for cf in _CONF_FILES:
        src = REPO_ROOT / "server-config" / cf
        if not src.exists():
            sys.exit(f"server-config/{cf} not found")
        (pkg_dir / cf).write_bytes(src.read_bytes())
    base_sh = REPO_ROOT / "server-config" / "setup.sh"
    if not base_sh.exists():
        sys.exit("server-config/setup.sh not found")
    setup = base_sh.read_text(encoding="utf-8")
    for hp in server.get("honeypots", []):
        frag = REPO_ROOT / "honey-pots" / hp / "deploy" / "setup" / "fragment.sh"
        if frag.exists():
            setup += f"\n\n# --- {hp} ---\n" + frag.read_text(encoding="utf-8")
        else:
            print(f"  Warning: no fragment.sh for '{hp}'", file=sys.stderr)
    for addon in server.get("addons", []):
        frag = REPO_ROOT / "addons" / addon / "deploy" / "setup" / "fragment.sh"
        if frag.exists():
            setup += f"\n\n# --- {addon} ---\n" + frag.read_text(encoding="utf-8")
        else:
            print(f"  Warning: no fragment.sh for addon '{addon}'", file=sys.stderr)
    with (pkg_dir / "setup.sh").open("w", encoding="utf-8", newline="\n") as f:
        f.write(setup)


def _scp(pkg_dir, key, pub_ip, *, retries=6, delay=10):
    args = scp_args(key, 22) + [str(pkg_dir), f"root@{pub_ip}:/root/"]
    for attempt in range(retries):
        r = subprocess.run(args)
        if r.returncode == 0:
            return
        if attempt < retries - 1:
            print(f"  SCP failed (attempt {attempt + 1}/{retries}), retrying in {delay}s...")
            time.sleep(delay)
    sys.exit(f"SCP failed after {retries} attempts")

# ── Provision one server ──────────────────────────────────────────────────────

def _provision(server, state, ts_api_key, *, grafana_password="",
               loki_host="", catalog_url="", vt_api_key="",
               triage_api_key="", force=False):
    name   = server["name"]
    stype  = server["type"]
    key    = ssh_key(server["ssh_key"])
    pub_ip = state.get(name, {}).get("public_ip")

    if not pub_ip:
        sys.exit(f"No public IP for '{name}' — run sync_ips.py after terraform apply")

    print(bold(f"\n{'─'*60}"))
    print(bold(f"  {name}  ({stype})  {pub_ip}"))
    print(bold(f"{'─'*60}"))

    existing_ts_ip = state.get(name, {}).get("tailscale_ip")
    if existing_ts_ip and not force:
        print(yellow(f"  '{name}' already has Tailscale IP {existing_ts_ip} in state.json"))
        ans = input("  Reprovision anyway? [y/N] ").strip().lower()
        if ans != "y":
            print(f"  Skipping '{name}'.")
            return existing_ts_ip

    ephemeral = server.get("tailscale_ephemeral", False)
    print(f"Generating {'ephemeral' if ephemeral else 'non-ephemeral'} Tailscale auth key...")
    ts_authkey = _gen_ts_key(ts_api_key, ephemeral=ephemeral)

    _await_ssh(pub_ip, key)

    with tempfile.TemporaryDirectory() as tmp:
        pkg_dir = Path(tmp) / name
        if stype == "backend":
            print("Staging backend package...")
            _stage_backend(server, pkg_dir)
        else:
            print("Assembling honeypot package...")
            _stage_honeypot(server, pkg_dir)
        print(f"Copying package to {pub_ip}...")
        _scp(pkg_dir, key, pub_ip)

    env = {"TS_AUTHKEY": ts_authkey}
    if name == "log-stack":
        env["GRAFANA_PASSWORD"] = grafana_password
    else:
        if loki_host:
            env["LOKI_HOST"] = loki_host
        if catalog_url and stype == "honeypot":
            env["CATALOG_URL"] = catalog_url
    if name == "malware-catalog":
        env["VT_API_KEY"] = vt_api_key
        env["TRIAGE_API_KEY"] = triage_api_key
    if stype == "honeypot":
        env["HONEYPOT_HOSTNAME"] = name

    env_prefix   = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    setup_remote = f"/root/{name}/setup/setup.sh" if stype == "backend" else f"/root/{name}/setup.sh"

    print("Running setup.sh (this takes several minutes)...")
    r = run_ssh(key, 22, pub_ip, f"{env_prefix} bash {setup_remote}", check=False)
    if r.returncode != 0:
        sys.exit(f"setup.sh failed on '{name}' (exit {r.returncode})")

    ts_ip = _poll_tailscale_ip(ts_api_key, name)
    if ts_ip:
        _write_tailscale_ip(name, ts_ip)
    else:
        print(yellow(f"  Warning: '{name}' did not appear in tailnet within 5 minutes."))
        print(yellow("  Run sync_ips.py manually to capture the Tailscale IP."))

    return ts_ip


def _write_tailscale_ip(name, ts_ip):
    state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    state.setdefault(name, {})["tailscale_ip"] = ts_ip
    _write_state(state)
    print(f"  state.json: {name} tailscale_ip = {ts_ip}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="End-to-end provisioning: terraform + server setup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python provision.py                         # full run: terraform + all servers\n"
            "  python provision.py --skip-terraform        # skip terraform, provision servers only\n"
            "  python provision.py --infra-only            # terraform + write state.json, then stop\n"
            "  python provision.py --server NAME           # provision one server (terraform still runs)\n"
            "  python provision.py --skip-terraform --force  # reprovision even already-provisioned servers"
        ),
    )
    parser.add_argument("--server", "-s", metavar="NAME",
                        help="Provision one server only (default: all in dependency order)")
    parser.add_argument("--skip-terraform", action="store_true",
                        help="Skip terraform phase; use existing state.json")
    parser.add_argument("--infra-only", action="store_true",
                        help="Run terraform + write state.json, then stop (no server setup)")
    parser.add_argument("--force", action="store_true",
                        help="Reprovision servers that already have a Tailscale IP in state.json")
    args = parser.parse_args()

    servers = load_manifest()

    # ── Collect secrets upfront so the run is fully unattended after this ─────
    linode_token = ""
    if not args.skip_terraform:
        tfvars = _TF_DIR / "terraform.tfvars"
        if not tfvars.exists():
            print("terraform/terraform.tfvars not found — need Linode API token.")
            linode_token = getpass.getpass("Linode API token: ").strip()
            if not linode_token:
                sys.exit("Linode API token is required.")

    # Determine which servers to provision
    if args.infra_only:
        targets = []
    elif args.server:
        targets = [s for s in servers if s["name"] == args.server]
        if not targets:
            sys.exit(f"Server '{args.server}' not found in honey-net.json")
    else:
        targets = servers

    # Backends first (manifest order), then honeypots
    ordered = (
        [s for s in targets if s["type"] == "backend"] +
        [s for s in targets if s["type"] == "honeypot"]
    )

    # ── Pre-flight: ensure SSH keys exist (generates missing ones) ───────────
    if ordered:
        print(bold("\nChecking SSH keys..."))
        for s in ordered:
            if s.get("ssh_key"):
                check_or_create(s["ssh_key"])

    ts_api_key       = ""
    grafana_password = ""
    vt_api_key       = ""
    triage_api_key   = ""
    if ordered:
        ts_api_key = _load_ts_api_key()
        if any(s["name"] == "log-stack" for s in ordered):
            print()
            grafana_password = getpass.getpass("Grafana admin password: ")
            if not grafana_password:
                sys.exit("Grafana admin password is required.")
        if any(s["name"] == "malware-catalog" for s in ordered):
            print("\n── malware-catalog enrichment keys (optional) ────────────────")
            vt_api_key = _load_optional_key(
                "VirusTotal API key",
                ".honey-net-vt-apikey",
                "virustotal.com/gui/my-apikey",
            )
            triage_api_key = _load_optional_key(
                "Triage API key",
                ".honey-net-triage-apikey",
                "tria.ge/account/api",
            )
            print("──────────────────────────────────────────────────────────────")

    # ── Phase 1: Terraform ────────────────────────────────────────────────────
    if args.skip_terraform:
        state_file = REPO_ROOT / "state.json"
        if not state_file.exists():
            sys.exit("state.json not found — run without --skip-terraform or run sync_ips.py first")
        state = json.loads(state_file.read_text(encoding="utf-8"))
    else:
        state = run_terraform(linode_token)

    if args.infra_only:
        print(green("\nInfrastructure ready. Run provision.py --skip-terraform to set up servers."))
        return

    if not ordered:
        return

    # ── Phase 2: Server setup ─────────────────────────────────────────────────
    print(f"\nProvisioning {len(ordered)} server(s):")
    for s in ordered:
        pub = state.get(s["name"], {}).get("public_ip", gray("(no public IP)"))
        print(f"  {s['name']:<25} {s['type']:<10} {pub}")

    # Seed from state in case backends were already provisioned in a prior run
    loki_host   = state.get("log-stack",       {}).get("tailscale_ip") or ""
    catalog_ip  = state.get("malware-catalog", {}).get("tailscale_ip") or ""
    catalog_url = f"http://{catalog_ip}:8000" if catalog_ip else ""

    for server in ordered:
        # Re-read state so each iteration sees Tailscale IPs written by the previous server
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))

        ts_ip = _provision(
            server, state, ts_api_key,
            grafana_password=grafana_password,
            loki_host=loki_host,
            catalog_url=catalog_url,
            vt_api_key=vt_api_key,
            triage_api_key=triage_api_key,
            force=args.force,
        )

        if server["name"] == "log-stack" and ts_ip:
            loki_host = ts_ip
            print(f"  LOKI_HOST → {loki_host}")
        if server["name"] == "malware-catalog" and ts_ip:
            catalog_url = f"http://{ts_ip}:8000"
            print(f"  CATALOG_URL → {catalog_url}")

    print(green(f"\nAll {len(ordered)} server(s) provisioned."))


if __name__ == "__main__":
    main()
