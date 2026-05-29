#!/usr/bin/env python3
"""Destroy all honey-net infrastructure: terraform destroy, Tailscale cleanup, state.json reset.

Steps (in order):
  1. terraform destroy — deletes all Linode VMs
  2. Tailscale cleanup — removes all honey-net nodes from the tailnet
  3. state.json reset — overwrites with {}

Usage:
  python teardown.py           # interactive confirmation
  python teardown.py --yes     # skip confirmation prompt
  python teardown.py --dry-run # show what would happen, make no changes
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.color import bold, green, red, yellow, gray
from lib.config import REPO_ROOT, load_manifest

_TF_DIR   = REPO_ROOT / "terraform"
_STATE_FILE = REPO_ROOT / "state.json"


# ── Tailscale helpers (mirror ts_cleanup.py) ──────────────────────────────────

def _load_api_key():
    import os
    key_file = Path.home() / ".tailscale-apikey"
    if key_file.exists():
        return key_file.read_text().strip()
    import getpass
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


def _get_devices(api_key):
    import requests
    resp = requests.get(
        "https://api.tailscale.com/api/v2/tailnet/-/devices",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code == 401:
        (Path.home() / ".tailscale-apikey").unlink(missing_ok=True)
        sys.exit(
            "Tailscale API key rejected (401). Generate a new one at tailscale.com.\n"
            "Removed stale key from ~/.tailscale-apikey"
        )
    resp.raise_for_status()
    return resp.json().get("devices", [])


def _delete_device(api_key, device_id):
    import requests
    resp = requests.delete(
        f"https://api.tailscale.com/api/v2/device/{device_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code == 401:
        sys.exit("Tailscale API key rejected during deletion.")
    resp.raise_for_status()


# ── Terraform destroy ─────────────────────────────────────────────────────────

def _terraform_destroy(dry_run):
    if not (_TF_DIR / ".terraform").exists():
        print(yellow("  terraform/ not initialised — skipping terraform destroy."))
        return True

    r = subprocess.run(
        ["terraform", f"-chdir={_TF_DIR}", "output", "-json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip() or r.stdout.strip() == "{}":
        print(gray("  No active Terraform resources — skipping terraform destroy."))
        return True

    if dry_run:
        print(yellow("  [dry-run] would run: terraform destroy -auto-approve"))
        return True

    print("\n[terraform] Destroying infrastructure...")
    r = subprocess.run([
        "terraform", f"-chdir={_TF_DIR}",
        "destroy", "-auto-approve", "-input=false",
    ])
    if r.returncode != 0:
        print(red("  terraform destroy failed."))
        return False
    print(green("  terraform destroy complete."))
    return True


# ── Tailscale cleanup ─────────────────────────────────────────────────────────

def _tailscale_cleanup(api_key, known_names, dry_run):
    print("\n[tailscale] Querying devices...")
    devices = _get_devices(api_key)
    targets = [d for d in devices if d.get("hostname", "") in known_names]

    if not targets:
        print(gray("  No honey-net nodes found in tailnet."))
        return

    for d in targets:
        hostname = d.get("hostname", "?")
        ts_ip    = next((a for a in d.get("addresses", []) if a.startswith("100.")), "?")
        print(f"  {red('✗') if not dry_run else yellow('?')} {hostname:<25}  {ts_ip}")

    if dry_run:
        print(yellow(f"\n  [dry-run] would remove {len(targets)} node(s) from Tailscale."))
        return

    print()
    removed = 0
    for d in targets:
        hostname = d.get("hostname", "?")
        print(f"  Removing {hostname} ...", end=" ", flush=True)
        try:
            _delete_device(api_key, d["id"])
            print(green("done"))
            removed += 1
        except Exception as e:
            print(red(f"failed: {e}"))

    print(green(f"\n  Removed {removed}/{len(targets)} node(s) from Tailscale."))


# ── state.json reset ──────────────────────────────────────────────────────────

def _reset_state(dry_run):
    if dry_run:
        print(yellow("\n  [dry-run] would overwrite state.json with {}"))
        return
    _STATE_FILE.write_text("{}\n", encoding="utf-8")
    print(green("\n  state.json cleared."))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Destroy all honey-net infrastructure and clear local state.",
    )
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without making any changes")
    args = parser.parse_args()

    servers     = load_manifest()
    known_names = {s["name"] for s in servers}

    print(bold("\n" + "─" * 60))
    print(bold("  HONEY-NET TEARDOWN"))
    print(bold("─" * 60))
    print(f"\n  Servers: {', '.join(sorted(known_names))}\n")
    print("  This will:")
    print("    1. terraform destroy  — delete all Linode VMs")
    print("    2. Tailscale cleanup  — remove all honey-net nodes from the tailnet")
    print("    3. state.json reset   — overwrite with {}")
    print()

    if args.dry_run:
        print(yellow("  DRY-RUN mode — no changes will be made.\n"))
    elif not args.yes:
        print(red("  WARNING: This action is irreversible."))
        try:
            ans = input("  Type \"destroy\" to confirm: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if ans != "destroy":
            print("Aborted.")
            sys.exit(0)
        print()

    api_key = _load_api_key()

    ok = _terraform_destroy(args.dry_run)
    if not ok:
        print(red("\nTerraform destroy failed — skipping Tailscale and state reset."))
        sys.exit(1)

    _tailscale_cleanup(api_key, known_names, args.dry_run)
    _reset_state(args.dry_run)

    if not args.dry_run:
        print(bold(green("\nTeardown complete.")))


if __name__ == "__main__":
    main()
