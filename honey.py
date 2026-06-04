#!/usr/bin/env python3
"""Launcher for honey-net control scripts."""

import importlib
import os
import sys
from pathlib import Path

# Re-exec with the venv Python if we're not already running from it.
# This lets `python honey.py` work without manually activating the venv.
_repo = Path(__file__).resolve().parent
_venv_python = _repo / ".venv" / "Scripts" / "python.exe"
if _venv_python.exists() and Path(sys.executable).resolve() != _venv_python.resolve():
    import subprocess
    sys.exit(subprocess.run([str(_venv_python)] + sys.argv).returncode)

# Make scripts/ importable as top-level modules (e.g. importlib.import_module("provision"))
_scripts = _repo / "scripts"
sys.path.insert(0, str(_scripts))

from lib.color import _enable_ansi, _c

_enable_ansi()

def _bold(t):  return _c("1",    t)
def _dim(t):   return _c("2",    t)
def _cyan(t):  return _c("36;1", t)

def _ask(prompt, default=False):
    """Prompt for a yes/no question; return bool. default=False means [y/N]."""
    hint = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"  {prompt} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default

def _provision_args():
    """Show server status and let the user pick which server to provision."""
    from lib.config import load_manifest
    import json
    servers = load_manifest()
    try:
        state = json.loads((_repo / "state.json").read_text(encoding="utf-8"))
    except Exception:
        state = {}

    print()
    for i, s in enumerate(servers, 1):
        entry  = state.get(s["name"], {})
        ts_ip  = entry.get("tailscale_ip")
        pub_ip = entry.get("public_ip")
        if ts_ip:
            status = _dim(f"live  {ts_ip}")
        elif pub_ip:
            status = f"VM exists, not set up  {pub_ip}"
        else:
            status = "not provisioned"
        print(f"  [{_cyan(str(i))}] {s['name']:<22} {status}")
    print(f"  [{_cyan('a')}] All servers\n")

    try:
        choice = input("  Select: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return []

    if choice == "a":
        args = []
    elif choice.isdigit() and 1 <= int(choice) <= len(servers):
        args = ["--server", servers[int(choice) - 1]["name"]]
    else:
        print("  Invalid — provisioning all.")
        args = []

    if _ask("Skip terraform? (VM already exists, just run server setup)"):
        args.append("--skip-terraform")
    return args

def _connect_args():
    pre = _ask("Pre-setup mode? (port 22, before setup.sh runs)")
    return ["--pre-setup"] if pre else []

def _gen_key_args():
    eph = _ask("Ephemeral key? (auto-removed from tailnet when offline)")
    return ["--ephemeral"] if eph else []

# (name, module, description, interactive-args-fn-or-None)
GROUPS = [
    ("Deploy", [
        ("provision",    "provision",    "End-to-end provisioning: terraform + server setup", _provision_args),
        ("deprovision",  "deprovision",  "Destroy one server's VM, clean Tailscale, clear state", None),
        ("redeploy",     "redeploy",     "Update a live server (port 65022, Tailscale)",  None),
        ("reconfigure",  "reconfigure",  "Re-apply host hardening config to a live server", None),
        ("teardown",     "teardown",     "Destroy VMs (terraform), clean Tailscale, clear state", None),
    ]),
    ("Ops", [
        ("connect",   "connect",   "Open an SSH session to a server",               _connect_args),
        ("sync",      "sync_ips",  "Sync IPs from Terraform + Tailscale to state.json", None),
        ("logs",      "get_logs",  "Pull logs from a honeypot server",              None),
        ("backup",    "backup",    "Back up logs, inbox, and malware catalog",       None),
        ("restore",   "restore",   "Restore a backup to the live network",           None),
    ]),
    ("Admin", [
        ("gen-key",        "gen_ts_key",       "Generate a Tailscale auth key",                  _gen_key_args),
        ("check-keys",     "check_ssh_keys",   "Check SSH keys in honey-net.json; generate missing", None),
        ("check-logs",     "check_logs",       "Check log stream freshness in Loki",             None),
        ("check-disk",     "check_disk",       "Check disk usage on all servers (25 GB Nanode limit)", None),
        ("test-loki",      "test_loki",        "Push a test log to Loki to verify the stack",    None),
        ("test",           "test_honeypot",    "Run smoke tests for a honeypot from this machine", None),
        ("ts-cleanup",     "ts_cleanup",       "Remove stale Tailscale nodes not in Terraform state", None),
        ("deploy-detector","deploy_detector",  "Deploy alerting detector to log-stack",           None),
    ]),
]

_CMD_MAP = {name: (module, desc, fn)
            for _, cmds in GROUPS
            for name, module, desc, fn in cmds}

def usage():
    print("Usage: python honey.py <command> [args...]\n")
    for group_name, cmds in GROUPS:
        print(f"{group_name}:")
        width = max(len(name) for name, *_ in cmds)
        for name, _, desc, *__ in cmds:
            print(f"  {name:<{width}}  {desc}")
        print()
    print("Pass --help to any command for its options.")

def _submenu(group_name, cmds):
    """Show commands in a group; return the chosen command name or None."""
    print(f"\n  {_bold(group_name)}\n")
    width = max(len(name) for name, *_ in cmds)
    for i, (name, _, desc, *__) in enumerate(cmds, 1):
        print(f"  {_cyan(str(i))}  {_bold(name):<{width + 9}}  {_dim(desc)}")
    print(f"  {_cyan('b')}  back\n")
    try:
        choice = input("  Select: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    if choice in ("b", "back"):
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(cmds):
        return cmds[int(choice) - 1][0]
    print("  Invalid selection.", file=sys.stderr)
    return None

def menu():
    """Show the top-level group menu; return a command name or None to loop."""
    print(f"\n  {_bold('Honey-Net')}\n")
    for i, (group_name, _) in enumerate(GROUPS, 1):
        print(f"  {_cyan(str(i))}  {group_name}")
    print(f"  {_cyan('q')}  quit\n")
    try:
        choice = input("  Select: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    if choice in ("q", "quit", "exit"):
        sys.exit(0)
    if choice.isdigit() and 1 <= int(choice) <= len(GROUPS):
        group_name, cmds = GROUPS[int(choice) - 1]
        return _submenu(group_name, cmds)
    print("  Invalid selection.", file=sys.stderr)
    return None

def dispatch(cmd):
    module, _, args_fn = _CMD_MAP[cmd]
    extra = args_fn() if args_fn else []
    sys.argv = [f"{module}.py"] + extra
    importlib.import_module(module).main()

def main():
    if len(sys.argv) < 2:
        while True:
            cmd = menu()
            if cmd is None:
                continue
            print()
            dispatch(cmd)
            print()
        return

    if sys.argv[1] in ("-h", "--help"):
        usage()
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd not in _CMD_MAP:
        print(f"Unknown command: {cmd!r}\n", file=sys.stderr)
        usage()
        sys.exit(1)

    module, _, _ = _CMD_MAP[cmd]
    sys.argv = [f"{module}.py"] + sys.argv[2:]
    importlib.import_module(module).main()

if __name__ == "__main__":
    main()
