#!/usr/bin/env python3
"""Launcher for honey-net control scripts."""

import importlib
import sys

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

def _connect_args():
    pre = _ask("Pre-setup mode? (port 22, before setup.sh runs)")
    return ["--pre-setup"] if pre else []

def _gen_key_args():
    eph = _ask("Ephemeral key? (auto-removed from tailnet when offline)")
    return ["--ephemeral"] if eph else []

# (name, module, description, interactive-args-fn-or-None)
COMMANDS = [
    ("deploy",     "deploy",         "First deploy to a server (port 22)",            None),
    ("redeploy",   "redeploy",       "Update a live server (port 65022, Tailscale)",  None),
    ("connect",    "connect",        "Open an SSH session to a server",               _connect_args),
    ("sync",       "sync_ips",       "Sync IPs from Terraform + Tailscale to state.json", None),
    ("logs",       "get_logs",       "Pull logs from a honeypot server",              None),
    ("gen-key",    "gen_ts_key",     "Generate a Tailscale auth key",                 _gen_key_args),
    ("check-keys",  "check_ssh_keys", "Check SSH keys in honey-net.json; generate missing",  None),
    ("check-logs",  "check_logs",     "Check log stream freshness in Loki",                  None),
]

_CMD_MAP = {name: (module, desc, fn) for name, module, desc, fn in COMMANDS}

def usage():
    print(f"Usage: python honey.py <command> [args...]\n")
    print("Commands:")
    width = max(len(name) for name, *_ in COMMANDS)
    for name, _, desc, *__ in COMMANDS:
        print(f"  {name:<{width}}  {desc}")
    print("\nPass --help to any command for its options.")

def menu():
    print(f"\n{_bold('Honey-Net')}\n")
    width = max(len(name) for name, *_ in COMMANDS)
    for i, (name, _, desc, *__) in enumerate(COMMANDS, 1):
        print(f"  {_cyan(str(i))}  {_bold(name):<{width + 9}}  {_dim(desc)}")
    print(f"  {_cyan('q')}  quit\n")
    try:
        choice = input("Select: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    if choice in ("q", "quit", "exit"):
        sys.exit(0)
    if not choice.isdigit() or not (1 <= int(choice) <= len(COMMANDS)):
        print("Invalid selection.\n", file=sys.stderr)
        return None
    return COMMANDS[int(choice) - 1][0]

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
