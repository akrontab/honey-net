"""Shared utilities for honey-net control-plane scripts."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    tomllib = None  # Python < 3.11; assemble_honeypot_package will error clearly

try:
    import yaml
except ImportError:
    yaml = None  # pyyaml not installed; assemble_honeypot_package will error clearly

REPO_ROOT = Path(__file__).parent
DEVNULL   = "NUL" if sys.platform == "win32" else "/dev/null"

# ── Colour output ─────────────────────────────────────────────────────────────

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
def yellow(t): return _c("33;1", t)
def gray(t):   return _c("2", t)
def bold(t):   return _c("1", t)

# ── Config loading ────────────────────────────────────────────────────────────

def load_manifest():
    path = REPO_ROOT / "honey-net.json"
    if not path.exists():
        sys.exit("honey-net.json not found")
    return json.loads(path.read_text(encoding="utf-8"))

def load_state():
    path = REPO_ROOT / "state.json"
    if not path.exists():
        sys.exit("state.json not found — run sync_ips.py after terraform apply")
    return json.loads(path.read_text(encoding="utf-8"))

# ── Server selection ──────────────────────────────────────────────────────────

def select_server(servers, state, name_arg=None, filter_fn=None, prompt="Select a server"):
    """Return a single server dict.

    If name_arg is given, look it up directly.
    Otherwise show a numbered menu filtered by filter_fn (or all servers).
    """
    candidates = [s for s in servers if filter_fn is None or filter_fn(s)]
    if not candidates:
        sys.exit("No matching servers found in honey-net.json")

    if name_arg:
        matches = [s for s in candidates if s["name"] == name_arg]
        if not matches:
            sys.exit(f"Server '{name_arg}' not found in honey-net.json")
        return matches[0]

    if len(candidates) == 1:
        return candidates[0]

    print(f"\n{prompt}:")
    for i, s in enumerate(candidates):
        e      = state.get(s["name"], {})
        pub_ip = e.get("public_ip")    or "(no public IP)"
        ts_ip  = e.get("tailscale_ip") or "(no Tailscale IP)"
        ports  = ", ".join(str(p) for p in s.get("ports", [])) or "none"
        hps    = ", ".join(s.get("honeypots", [])) or "-"
        print(f"  [{i}] {s['name']:<25} type={s['type']:<10} "
              f"ports={ports:<12} public={pub_ip:<16} tailscale={ts_ip}")
    print()
    choice = input("Enter number: ").strip()
    if not choice.isdigit() or int(choice) >= len(candidates):
        sys.exit("Invalid selection")
    return candidates[int(choice)]

# ── SSH helpers ───────────────────────────────────────────────────────────────

def ssh_key(raw):
    return str(Path(raw.replace("~", str(Path.home()))))

def ssh_base_args(key, port, ip):
    return [
        "ssh", "-i", key, "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={DEVNULL}",
        f"root@{ip}",
    ]

def scp_args(key, port):
    return [
        "scp", "-r", "-P", str(port), "-i", key,
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={DEVNULL}",
    ]

def run_ssh(key, port, ip, cmd, check=True, capture=False):
    args = ssh_base_args(key, port, ip) + [cmd]
    if capture:
        r = subprocess.run(args, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return subprocess.run(args, check=check)

# ── File helpers ──────────────────────────────────────────────────────────────

def copy_tree(src, dst, exclude_names=None):
    """Recursively copy src → dst, skipping files whose names are in exclude_names."""
    exclude = set(exclude_names or [])
    def _ignore(_, names):
        return {n for n in names if n in exclude}
    shutil.copytree(src, dst, ignore=_ignore)

# ── Honeypot package assembly ─────────────────────────────────────────────────

def _extract_vector_mounts(hp_name, volumes):
    """
    Convert a honeypot vector service's volume list into log mounts for the
    merged top-level vector service.  Relative paths are re-rooted under
    hp_name/; the three shared mounts (hostlogs, vector.toml, vector-data)
    are skipped because the caller adds them once.
    """
    mounts = []
    for vol in volumes:
        if not isinstance(vol, str):
            continue
        if "vector.toml" in vol or vol == "vector-data:/vector-data" or vol.startswith("/var/log:"):
            continue
        if vol.startswith("./"):
            mounts.append(f"./{hp_name}/{vol[2:]}")
        else:
            mounts.append(vol)  # named volume (e.g. analyzer-logs:/logs/malware:ro)
    return mounts


def _merge_vector_tomls(toml_paths):
    """Parse and merge multiple vector.toml files, deduplicating by source/sink key."""
    if tomllib is None:
        sys.exit("Python 3.11+ is required (tomllib). Upgrade Python and re-run setup.")
    sources, sinks = {}, {}
    for path in toml_paths:
        if not path.exists():
            continue
        with open(path, "rb") as f:
            data = tomllib.load(f)
        for k, v in data.get("sources", {}).items():
            sources.setdefault(k, v)
        for k, v in data.get("sinks", {}).items():
            sinks.setdefault(k, v)
    return sources, sinks


def _toml_scalar(v):
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(_toml_scalar(i) for i in v) + "]"
    return str(v)


def _write_toml_block(lines, prefix, block):
    for k, v in block.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_scalar(v)}")
    for k, sub in block.items():
        if isinstance(sub, dict):
            lines.append(f"\n[{prefix}.{k}]")
            _write_toml_block(lines, f"{prefix}.{k}", sub)


def _write_merged_vector_toml(path, sources, sinks):
    lines = ['data_dir = "/vector-data"', "", "# ── Sources " + "─" * 52]
    for name, fields in sources.items():
        lines += ["", f"[sources.{name}]"]
        _write_toml_block(lines, f"sources.{name}", fields)
    lines += ["", "", "# ── Sinks " + "─" * 54]
    for name, fields in sinks.items():
        lines += ["", f"[sinks.{name}]"]
        _write_toml_block(lines, f"sinks.{name}", fields)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assemble_honeypot_package(server, pkg_dir):
    """
    Populates pkg_dir with the honeypot deploy package:
      - <hp>/  — each honeypot's deploy files, with vector service stripped from compose
      - vector/vector.toml — merged from all honeypots (sources/sinks deduplicated)
      - docker-compose.yml — include: per honeypot + single merged vector service

    pkg_dir must already exist.  Does NOT generate setup.sh or copy server-config
    files (deploy.py handles those extras for first deploy).
    """
    if yaml is None:
        sys.exit("pyyaml is required — run setup.ps1 or setup.sh to reinstall dependencies")

    honeypots = server["honeypots"]
    vector_mounts = []  # accumulated log-path mounts across all honeypots

    for hp in honeypots:
        src = REPO_ROOT / "honey-pots" / hp / "deploy"
        if not src.exists():
            sys.exit(f"Honeypot deploy folder not found: {src}")
        copy_tree(src, pkg_dir / hp, exclude_names={".env"})

        compose_path = pkg_dir / hp / "docker-compose.yml"
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        vector_svc = compose.get("services", {}).pop("vector", {})
        vector_mounts += _extract_vector_mounts(hp, vector_svc.get("volumes", []))

        # vector-data is now owned by the top-level compose
        compose.get("volumes", {}).pop("vector-data", None)

        compose_path.write_text(
            yaml.safe_dump(compose, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    # Merge vector.toml files from all honeypots
    toml_paths = [pkg_dir / hp / "vector" / "vector.toml" for hp in honeypots]
    sources, sinks = _merge_vector_tomls(toml_paths)
    (pkg_dir / "vector").mkdir(exist_ok=True)
    _write_merged_vector_toml(pkg_dir / "vector" / "vector.toml", sources, sinks)

    # Build volume list for the single merged vector service
    all_volumes = vector_mounts + [
        "/var/log:/hostlogs:ro",
        "./vector/vector.toml:/etc/vector/vector.toml:ro",
        "vector-data:/vector-data",
    ]
    vol_lines  = "\n".join(f"      - {v}" for v in all_volumes)
    inc_lines  = "\n".join(f"  - path: {hp}/docker-compose.yml" for hp in honeypots)

    compose_text = (
        "# Generated by honey-net control plane — do not edit on the server.\n"
        "# Source of truth: honey-net.json and honey-pots/<name>/deploy/\n"
        "\n"
        f"include:\n{inc_lines}\n"
        "\n"
        "services:\n"
        "  vector:\n"
        "    image: timberio/vector:0.42.0-alpine\n"
        "    container_name: vector\n"
        "    restart: unless-stopped\n"
        "    user: root\n"
        '    command: ["--config", "/etc/vector/vector.toml"]\n'
        "    volumes:\n"
        f"{vol_lines}\n"
        "    environment:\n"
        "      - LOKI_HOST=${LOKI_HOST}\n"
        "      - HOSTNAME=${HONEYPOT_HOSTNAME}\n"
        "    networks:\n"
        "      - honeypot\n"
        "\n"
        "volumes:\n"
        "  vector-data:\n"
    )
    (pkg_dir / "docker-compose.yml").write_text(compose_text, encoding="utf-8")
