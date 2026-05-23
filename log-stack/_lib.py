"""Shared utilities for log-stack scripts."""

import json
import sys
from pathlib import Path

# log-stack/ lives one level inside the honey-net repo root
LOGSTACK_ROOT = Path(__file__).parent
HONEYSET_ROOT = LOGSTACK_ROOT.parent

DEVNULL = "NUL" if sys.platform == "win32" else "/dev/null"

def _enable_ansi():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

_COLOR = sys.stdout.isatty()
_enable_ansi()

def _c(code, text): return f"\033[{code}m{text}\033[0m" if _COLOR else text
def green(t):  return _c("32;1", t)
def red(t):    return _c("31;1", t)

def load_manifest():
    path = HONEYSET_ROOT / "honey-net.json"
    if not path.exists():
        sys.exit(f"honey-net.json not found at {HONEYSET_ROOT}")
    return json.loads(path.read_text(encoding="utf-8"))

def load_state():
    path = HONEYSET_ROOT / "state.json"
    if not path.exists():
        sys.exit(f"state.json not found at {HONEYSET_ROOT} — run sync_ips.py after terraform apply")
    return json.loads(path.read_text(encoding="utf-8"))

def select_backend(servers, state, prompt="Select a log-stack server"):
    candidates = [s for s in servers if s["type"] == "backend"]
    if not candidates:
        sys.exit("No backend servers found in honey-net.json")
    if len(candidates) == 1:
        return candidates[0]
    print(f"\n{prompt}:")
    for i, s in enumerate(candidates):
        ts_ip = state.get(s["name"], {}).get("tailscale_ip") or "(none)"
        print(f"  [{i}] {s['name']:<20} tailscale={ts_ip}")
    print()
    choice = input("Enter number: ").strip()
    if not choice.isdigit() or int(choice) >= len(candidates):
        sys.exit("Invalid selection")
    return candidates[int(choice)]

def ssh_key(raw):
    return str(Path(raw.replace("~", str(Path.home()))))
