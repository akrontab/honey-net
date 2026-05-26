#!/usr/bin/env python3
"""Generates a new Tailscale auth key via the Tailscale API."""

import argparse
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(
        description="Generate a Tailscale auth key for a new honey-net host."
    )
    parser.add_argument("--ephemeral", action="store_true",
                        help="Create an ephemeral key (node auto-removes when offline)")
    parser.add_argument("--expiry-days", type=int, default=90, metavar="N",
                        help="Key expiry in days (default: 90)")
    args = parser.parse_args()

    import requests

    api_key_file = Path.home() / ".tailscale-apikey"

    if api_key_file.exists():
        api_key = api_key_file.read_text().strip()
    else:
        print(f"No API key found at {api_key_file}")
        print("Generate one at: tailscale.com → Settings → Keys → Generate API key")
        print()
        api_key = input("Paste your Tailscale API key: ").strip()
        if not api_key:
            sys.exit("API key is required")
        save = input(f"Save to {api_key_file} for future use? [y/N] ").strip().lower()
        if save == "y":
            api_key_file.write_text(api_key)
            try:
                os.chmod(api_key_file, 0o600)
            except Exception:
                print(f"Note: could not restrict permissions on {api_key_file} — check manually")
            print("Saved.")

    body = {
        "capabilities": {
            "devices": {
                "create": {
                    "reusable":      False,
                    "ephemeral":     args.ephemeral,
                    "preauthorized": False,
                    "tags":          [],
                }
            }
        },
        "expirySeconds": args.expiry_days * 86400,
    }

    try:
        resp = requests.post(
            "https://api.tailscale.com/api/v2/tailnet/-/keys",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=10,
        )
        if resp.status_code == 401:
            api_key_file.unlink(missing_ok=True)
            sys.exit(
                "API key rejected (401). Generate a new one at tailscale.com → Settings → Keys.\n"
                f"Removed stale key from {api_key_file}"
            )
        resp.raise_for_status()
    except requests.RequestException as e:
        sys.exit(f"Tailscale API error: {e}")

    data       = resp.json()
    expires    = data["expires"][:10]
    ephemeral_label = " ephemeral," if args.ephemeral else ""

    print(f"\nTailscale auth key ({ephemeral_label} expires {expires}):\n")
    print(f"  {data['key']}\n")
    if args.ephemeral:
        print("This node will be automatically removed from the tailnet when it goes offline.")
    else:
        print("Use this as TS_AUTHKEY when running setup.sh on a new host.")

if __name__ == "__main__":
    main()
