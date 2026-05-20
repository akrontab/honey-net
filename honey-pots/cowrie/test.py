#!/usr/bin/env python3
"""Smoke-tests a running Cowrie deployment."""

import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from _lib import DEVNULL, green, red, yellow, gray, load_manifest, load_state, select_server, ssh_key

MGMT_PORT = 65022

def main():
    servers = load_manifest()
    state   = load_state()
    server  = select_server(
        servers, state,
        filter_fn=lambda s: "cowrie" in s.get("honeypots", []),
        prompt="Select a server to test",
    )

    name   = server["name"]
    key    = ssh_key(server["ssh_key"])
    entry  = state.get(name, {})
    pub_ip = entry.get("public_ip")
    ts_ip  = entry.get("tailscale_ip")

    if not pub_ip:
        sys.exit(f"No public IP for '{name}' in state.json — run sync_ips.py after terraform apply")

    print(f"\nTesting: {name}")
    print(f"  Public IP   : {pub_ip}")
    print(f"  Tailscale IP: {ts_ip or '(none — management tests will be skipped)'}\n")

    passed = failed = skipped = 0

    def ok(msg):   nonlocal passed;  passed  += 1; print(f"  {green('[PASS]')} {msg}")
    def fail(msg): nonlocal failed;  failed  += 1; print(f"  {red('[FAIL]')} {msg}")
    def skip(msg): nonlocal skipped; skipped += 1; print(f"  {yellow('[SKIP]')} {msg}")
    def info(msg):                                  print(f"  {gray('      ')} {gray(msg)}")

    # ── Test 1: Port 22 reachable ─────────────────────────────────────────────
    print("[ 1 ] Port 22 reachable (honeypot SSH)")
    try:
        with socket.create_connection((pub_ip, 22), timeout=3):
            ok("Port 22 is open")
    except Exception as e:
        fail(f"Port 22 not reachable ({e})")

    # ── Test 2: SSH banner ────────────────────────────────────────────────────
    print("\n[ 2 ] SSH banner")
    try:
        with socket.create_connection((pub_ip, 22), timeout=3) as s:
            s.settimeout(3)
            banner = s.recv(512).decode("ascii", errors="replace").strip()
        info(f"Banner: {banner}")
        if "OpenSSH_8.9p1 Ubuntu" in banner:
            ok("Banner matches expected fake AWS version")
        else:
            fail("Banner does not match expected value")
    except Exception as e:
        fail(f"Could not read SSH banner ({e})")

    # ── Tests 3-5 require Tailscale IP ───────────────────────────────────────
    if not ts_ip:
        print()
        skip(f"Port {MGMT_PORT} reachable — no Tailscale IP (run sync_ips.py after setup.sh)")
        skip("Container status — no Tailscale IP")
        skip("Cowrie log file — no Tailscale IP")
    else:
        ssh = ["ssh", "-i", key, "-p", str(MGMT_PORT),
               "-o", "StrictHostKeyChecking=no", "-o", f"UserKnownHostsFile={DEVNULL}",
               f"root@{ts_ip}"]

        # ── Test 3: Management port ───────────────────────────────────────────
        print(f"\n[ 3 ] Management port {MGMT_PORT} reachable (Tailscale)")
        try:
            with socket.create_connection((ts_ip, MGMT_PORT), timeout=3):
                ok(f"Port {MGMT_PORT} is open")
        except Exception as e:
            fail(f"Port {MGMT_PORT} not reachable ({e})")

        # ── Test 4: Container running ─────────────────────────────────────────
        print("\n[ 4 ] Cowrie container status")
        r = subprocess.run(
            ssh + ["docker ps --filter name=cowrie --format '{{.Status}}'"],
            capture_output=True, text=True,
        )
        status = r.stdout.strip()
        if status.startswith("Up"):
            ok(f"Container is running ({status})")
        else:
            fail(f"Container not running (got: '{status}')")

        # ── Test 5: Log file ──────────────────────────────────────────────────
        print("\n[ 5 ] Cowrie JSON log")
        log_path  = f"/opt/{name}/cowrie/volumes/var/log/cowrie/cowrie.json"
        r = subprocess.run(
            ssh + [f"wc -l < {log_path} 2>/dev/null || echo MISSING"],
            capture_output=True, text=True,
        )
        result = r.stdout.strip()
        if result == "MISSING":
            fail(f"Log file not found at {log_path}")
        else:
            ok(f"Log file exists ({result} lines)")
            info("Last 3 events:")
            r2 = subprocess.run(ssh + [f"tail -3 {log_path}"], capture_output=True, text=True)
            for line in r2.stdout.strip().splitlines():
                info(line)

    print(f"\n{'─' * 36}")
    print(f"  {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'─' * 36}")
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
