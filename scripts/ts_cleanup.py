#!/usr/bin/env python3
"""Remove stale Tailscale nodes that no longer have a matching Terraform resource."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.color import bold, green, red, yellow, gray
from lib.config import REPO_ROOT, load_manifest


def _load_api_key():
    ts_key_file = Path.home() / ".tailscale-apikey"
    if ts_key_file.exists():
        return ts_key_file.read_text().strip()

    print(f"No API key found at {ts_key_file}")
    print("Generate one at: tailscale.com → Settings → Keys → Generate API key")
    print()
    api_key = input("Paste your Tailscale API key: ").strip()
    if not api_key:
        sys.exit("API key is required")
    save = input(f"Save to {ts_key_file} for future use? [y/N] ").strip().lower()
    if save == "y":
        ts_key_file.write_text(api_key)
        try:
            os.chmod(ts_key_file, 0o600)
        except Exception:
            print(f"Note: could not restrict permissions on {ts_key_file} — check manually")
        print("Saved.")
    return api_key


def _get_tf_active_names():
    """Return set of server names currently tracked by Terraform, or None if unavailable."""
    tf_dir = REPO_ROOT / "terraform"
    if not (tf_dir / ".terraform").exists():
        return None

    r = subprocess.run(
        ["terraform", f"-chdir={tf_dir}", "output", "-json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None

    raw = r.stdout.strip()
    if not raw or raw == "{}":
        return set()

    outputs = json.loads(raw)
    return set(outputs.get("server_ips", {}).get("value", {}).keys())


def _get_devices(api_key):
    import requests
    resp = requests.get(
        "https://api.tailscale.com/api/v2/tailnet/-/devices",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code == 401:
        Path.home().joinpath(".tailscale-apikey").unlink(missing_ok=True)
        sys.exit(
            "Tailscale API key rejected (401). Generate a new one at tailscale.com → Settings → Keys.\n"
            "Removed stale key from ~/.tailscale-apikey"
        )
    resp.raise_for_status()
    return resp.json().get("devices", [])


def _delete_device(api_key, device_id, hostname):
    import requests
    resp = requests.delete(
        f"https://api.tailscale.com/api/v2/device/{device_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code == 401:
        sys.exit("API key rejected during deletion.")
    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser(
        description="Remove stale Tailscale nodes not in active Terraform state."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show stale nodes without deleting them")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt")
    args = parser.parse_args()

    api_key = _load_api_key()

    servers = load_manifest()
    known_names = {s["name"] for s in servers}

    # Determine which servers are currently active in Terraform
    print("Reading Terraform state...")
    active_names = _get_tf_active_names()
    if active_names is None:
        print(yellow("Warning: Terraform not initialised or unavailable."))
        print("  Falling back to honey-net.json — all declared servers treated as active.")
        print("  Run 'terraform init' and 'terraform apply' to enable Terraform-based comparison.\n")
        active_names = known_names
    else:
        label = ", ".join(sorted(active_names)) if active_names else "(none)"
        print(f"  Active in Terraform: {label}\n")

    # Fetch Tailscale devices
    print("Querying Tailscale devices...")
    devices = _get_devices(api_key)
    print(f"  {len(devices)} device(s) in tailnet\n")

    # A device is stale if its hostname matches a known honey-net server name
    # but that server is no longer active in Terraform (was destroyed).
    stale = [
        d for d in devices
        if d.get("hostname", "") in known_names
        and d.get("hostname", "") not in active_names
    ]

    # Separately note unknown devices (not honey-net names) so the operator knows
    # they're being skipped intentionally.
    unknown = [d for d in devices if d.get("hostname", "") not in known_names]
    if unknown:
        names = ", ".join(d.get("hostname", "?") for d in unknown)
        print(gray(f"  Skipping {len(unknown)} non-honey-net device(s): {names}"))
        print()

    if not stale:
        print(green("No stale honey-net nodes found in Tailscale."))
        return

    print(bold(f"Stale nodes ({len(stale)}) — in Tailscale but not in Terraform state:"))
    print()
    for device in stale:
        hostname  = device.get("hostname", "?")
        ts_ip     = next((a for a in device.get("addresses", []) if a.startswith("100.")), "?")
        last_seen = device.get("lastSeen", "")[:19].replace("T", " ") or "unknown"
        print(f"  {red('✗')} {hostname:<25}  {ts_ip:<16}  last seen {last_seen}")
    print()

    if args.dry_run:
        print(yellow("[dry-run] No changes made."))
        return

    if not args.yes:
        try:
            ans = input(f"Remove {len(stale)} stale node(s) from Tailscale? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if ans not in ("y", "yes"):
            print("Aborted.")
            return
        print()

    for device in stale:
        hostname = device.get("hostname", "?")
        print(f"  Removing {hostname} ...", end=" ", flush=True)
        try:
            _delete_device(api_key, device["id"], hostname)
            print(green("done"))
        except Exception as e:
            print(red(f"failed: {e}"))

    print(f"\nDone — removed {len(stale)} stale node(s).")


if __name__ == "__main__":
    main()
