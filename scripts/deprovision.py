#!/usr/bin/env python3
"""Deprovision a single honey-net server: destroy VM, clean Tailscale, clear state.

honey-net.json is NOT modified, so the server can be reprovisioned immediately
with: python honey.py provision --server <name>

Usage:
  python deprovision.py                # interactive server selection
  python deprovision.py --server NAME  # target a specific server
  python deprovision.py --dry-run      # show what would happen, make no changes
  python deprovision.py --yes          # skip confirmation prompt
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.color import bold, green, red, yellow, gray
from lib.config import REPO_ROOT, load_manifest, load_state
from lib.server import select_server

_TF_DIR     = REPO_ROOT / "terraform"
_STATE_FILE = REPO_ROOT / "state.json"


# ── Tailscale helpers ─────────────────────────────────────────────────────────

def _load_ts_api_key():
    import getpass
    key_file = Path.home() / ".tailscale-apikey"
    if key_file.exists():
        return key_file.read_text().strip()
    print("No Tailscale API key found at ~/.tailscale-apikey")
    print("Generate one at: tailscale.com → Settings → Keys → Generate API key\n")
    key = getpass.getpass("Tailscale API key: ").strip()
    if not key:
        sys.exit("Tailscale API key is required.")
    if input(f"Save to {key_file} for future use? [y/N] ").strip().lower() == "y":
        key_file.write_text(key)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        print("Saved.")
    return key


def _tailscale_cleanup(api_key, name, dry_run):
    import requests
    print(f"\n[tailscale] Looking for '{name}'...")
    resp = requests.get(
        "https://api.tailscale.com/api/v2/tailnet/-/devices",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code == 401:
        (Path.home() / ".tailscale-apikey").unlink(missing_ok=True)
        sys.exit("Tailscale API key rejected (401). Generate a new one at tailscale.com.")
    resp.raise_for_status()

    device = next(
        (d for d in resp.json().get("devices", []) if d.get("hostname") == name),
        None,
    )
    if device is None:
        print(gray(f"  '{name}' not found in tailnet (may already be gone)."))
        return

    ts_ip = next((a for a in device.get("addresses", []) if a.startswith("100.")), "?")
    print(f"  Found: {name}  {ts_ip}")
    if dry_run:
        print(yellow(f"  [dry-run] would remove '{name}' from Tailscale."))
        return

    requests.delete(
        f"https://api.tailscale.com/api/v2/device/{device['id']}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    ).raise_for_status()
    print(green(f"  Removed '{name}' from Tailscale."))


# ── Terraform ─────────────────────────────────────────────────────────────────

def _terraform_destroy_target(name, dry_run):
    if not (_TF_DIR / ".terraform").exists():
        print(yellow("  terraform/ not initialised — skipping VM destroy."))
        return True

    target = f'module.host["{name}"]'
    if dry_run:
        print(yellow(f"  [dry-run] would run: terraform destroy -target={target}"))
        return True

    print(f"\n[terraform] Destroying {name} VM...")
    r = subprocess.run([
        "terraform", f"-chdir={_TF_DIR}",
        "destroy", "-auto-approve", "-input=false",
        f"-target={target}",
    ])
    if r.returncode != 0:
        print(red("  terraform destroy failed."))
        return False
    print(green(f"  {name} VM destroyed."))
    return True


# ── state.json / honey-net.json ───────────────────────────────────────────────

def _clear_state(name, dry_run):
    state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    if name not in state:
        print(gray(f"\n  '{name}' not in state.json — nothing to clear."))
        return
    if dry_run:
        print(yellow(f"\n  [dry-run] would remove '{name}' from state.json."))
        return
    del state[name]
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, _STATE_FILE)
    print(green(f"\n  Removed '{name}' from state.json."))


def _remove_from_manifest(name, dry_run):
    manifest_path = REPO_ROOT / "honey-net.json"
    servers = json.loads(manifest_path.read_text(encoding="utf-8"))
    updated = [s for s in servers if s["name"] != name]
    if len(updated) == len(servers):
        print(gray(f"  '{name}' not found in honey-net.json — nothing to remove."))
        return
    if dry_run:
        print(yellow(f"  [dry-run] would remove '{name}' from honey-net.json."))
        return
    with manifest_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(updated, indent=2) + "\n")
    print(green(f"  Removed '{name}' from honey-net.json."))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Deprovision a single honey-net server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "honey-net.json is NOT modified — run provision again to recreate the server.\n\n"
            "examples:\n"
            "  python deprovision.py --server smb-ftp\n"
            "  python deprovision.py --server smb-ftp --dry-run"
        ),
    )
    parser.add_argument("--server", "-s", metavar="NAME")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--keep-config", action="store_true",
                        help="Keep honey-net.json entry (useful for 'replace VM' workflow)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without making any changes")
    args = parser.parse_args()

    servers = load_manifest()
    state   = load_state()
    server  = select_server(servers, state, name_arg=args.server,
                            prompt="Select a server to deprovision")
    name      = server["name"]
    ephemeral = server.get("tailscale_ephemeral", False)
    entry     = state.get(name, {})
    pub_ip    = entry.get("public_ip")    or gray("(none)")
    ts_ip     = entry.get("tailscale_ip") or gray("(none)")

    print(bold(f"\n{'─' * 60}"))
    print(bold(f"  DEPROVISION: {name}"))
    print(bold(f"{'─' * 60}"))
    print(f"\n  Public IP   : {pub_ip}")
    print(f"  Tailscale IP: {ts_ip}")
    print()
    remove_config = not args.keep_config
    if not args.yes and not args.dry_run:
        try:
            ans = input("  Remove from honey-net.json too? [y/N]: ").strip().lower()
            remove_config = ans in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

    print()
    print("  This will:")
    print(f"    1. terraform destroy -target=module.host[\"{name}\"]  — delete the VM")
    step = 2
    if not ephemeral:
        print(f"    {step}. Remove '{name}' from Tailscale")
        step += 1
    else:
        print(f"       (Tailscale node is ephemeral — auto-removed when VM dies)")
    print(f"    {step}. Remove '{name}' from state.json")
    step += 1
    if remove_config:
        print(f"    {step}. Remove '{name}' from honey-net.json")
    else:
        print(f"       honey-net.json unchanged  (run provision to recreate)")
    print()

    if args.dry_run:
        print(yellow("  DRY-RUN mode — no changes will be made.\n"))
    elif not args.yes:
        print(red("  WARNING: All data on the VM will be lost."))
        try:
            ans = input(f'  Type "{name}" to confirm: ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if ans != name:
            print("Aborted.")
            sys.exit(0)
        print()
    else:
        remove_config = not args.keep_config

    api_key = _load_ts_api_key()

    ok = _terraform_destroy_target(name, args.dry_run)
    if not ok:
        sys.exit(1)

    if not ephemeral:
        _tailscale_cleanup(api_key, name, args.dry_run)
    else:
        print(gray(f"\n[tailscale] Skipping — '{name}' is ephemeral."))

    _clear_state(name, args.dry_run)

    if remove_config:
        _remove_from_manifest(name, args.dry_run)

    if not args.dry_run:
        print(bold(green(f"\n{name} deprovisioned.")))
        if not remove_config:
            print(f"\n  To reprovision:  python honey.py provision --server {name}")


if __name__ == "__main__":
    main()
