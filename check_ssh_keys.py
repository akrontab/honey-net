#!/usr/bin/env python3
"""Checks SSH keys in honey-net.json and generates any that are missing."""

import subprocess
import sys
from pathlib import Path

from lib.color import bold, green, red, yellow
from lib.config import load_manifest
from lib.ssh import ssh_key


def check_or_create(raw_path: str) -> None:
    path = Path(ssh_key(raw_path))
    pub  = path.with_suffix(".pub")
    name = path.name

    if path.exists() and pub.exists():
        print(f"  {green('ok')}      {name}  ({path})")
        return

    if path.exists() and not pub.exists():
        print(f"  {yellow('warn')}    {name} — private key exists but .pub is missing")
        return

    print(f"  {yellow('missing')} {name}  ({path}) — generating...")
    path.parent.mkdir(parents=True, exist_ok=True)

    r = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  {red('error')}   ssh-keygen failed:\n{r.stderr.strip()}", file=sys.stderr)
        return

    print(f"  {green('created')} {name}")
    print(f"           Public key: {pub.read_text().strip()}")


def main():
    servers = load_manifest()

    print(bold("\nSSH key status:"))
    print()
    for s in servers:
        raw = s.get("ssh_key", "")
        if not raw:
            print(f"  {yellow('skip')}    {s['name']} — no ssh_key field")
            continue
        print(f"  {bold(s['name'])}")
        check_or_create(raw)
    print()


if __name__ == "__main__":
    main()
