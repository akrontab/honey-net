#!/usr/bin/env python3
"""Reads Terraform outputs and Tailscale device IPs, writes state.json."""

import json
import subprocess
import sys
from pathlib import Path

from lib.color import bold
from lib.config import REPO_ROOT, load_manifest

def main():
    tf_dir     = REPO_ROOT / "terraform"
    state_file = REPO_ROOT / "state.json"
    ts_key_file = Path.home() / ".tailscale-apikey"

    if not (tf_dir / ".terraform").exists():
        sys.exit("Terraform not initialised — run: cd terraform && terraform init")

    servers = load_manifest()

    # ── Public IPs from Terraform ─────────────────────────────────────────────
    print("Reading terraform outputs...")
    r = subprocess.run(
        ["terraform", f"-chdir={tf_dir}", "output", "-json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit(f"terraform output failed — has terraform apply been run?\n{r.stderr.strip()}")

    raw = r.stdout.strip()
    if not raw or raw == "{}":
        sys.exit("terraform output returned no values — run terraform apply first")

    outputs    = json.loads(raw)
    public_ips = outputs["server_ips"]["value"]

    # ── Tailscale IPs via API ─────────────────────────────────────────────────
    import requests

    ts_devices = {}
    if ts_key_file.exists():
        ts_key = ts_key_file.read_text().strip()
        try:
            resp = requests.get(
                "https://api.tailscale.com/api/v2/tailnet/-/devices",
                headers={"Authorization": f"Bearer {ts_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            for device in resp.json().get("devices", []):
                ts_ip = next(
                    (a for a in device.get("addresses", []) if a.startswith("100.")),
                    None,
                )
                if ts_ip:
                    ts_devices[device["hostname"]] = ts_ip
            print(f"Tailscale: {len(ts_devices)} device(s) found in tailnet")
        except Exception as e:
            print(f"Warning: Tailscale API call failed — Tailscale IPs will be null.\n  {e}",
                  file=sys.stderr)
    else:
        print(f"Warning: {ts_key_file} not found — Tailscale IPs will be null.\n"
              "  Generate one at tailscale.com → Settings → Keys → Generate API key",
              file=sys.stderr)

    # ── Build state.json ──────────────────────────────────────────────────────
    state = {}
    for server in servers:
        name      = server["name"]
        public_ip = public_ips.get(name)
        if not public_ip:
            print(f"Warning: no terraform output for '{name}' — skipping", file=sys.stderr)
            continue

        ts_ip      = ts_devices.get(name)
        ts_display = ts_ip or "(not in tailnet yet)"
        state[name] = {"public_ip": public_ip, "tailscale_ip": ts_ip}
        print(f"  {name:<25} public={public_ip:<16} tailscale={ts_display}")

    state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print("\nstate.json written.")
    if not ts_devices:
        print("Re-run after servers have joined Tailscale to populate tailscale_ip entries.")

if __name__ == "__main__":
    main()
