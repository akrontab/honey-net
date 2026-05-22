import json
import sys

try:
    import tomllib
except ImportError:
    tomllib = None  # Python < 3.11; assemble_honeypot_package will error clearly

try:
    import yaml
except ImportError:
    yaml = None  # pyyaml not installed; assemble_honeypot_package will error clearly

from lib.config import REPO_ROOT
from lib.files import copy_tree


# ── Vector TOML helpers ───────────────────────────────────────────────────────

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


# ── Assembly steps ────────────────────────────────────────────────────────────

def _stage_component(name, base, pkg_dir):
    """Copy one component's deploy files, strip its vector service from the compose.

    Returns the vector log mounts extracted from the stripped service so the
    caller can accumulate them for the merged top-level vector service.
    """
    src = REPO_ROOT / base / name / "deploy"
    if not src.exists():
        sys.exit(f"Deploy folder not found: {src}")
    copy_tree(src, pkg_dir / name, exclude_names={".env"})

    compose_path = pkg_dir / name / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    vector_svc = compose.get("services", {}).pop("vector", {})
    mounts = _extract_vector_mounts(name, vector_svc.get("volumes", []))

    # vector-data is owned by the top-level compose
    compose.get("volumes", {}).pop("vector-data", None)

    compose_path.write_text(
        yaml.safe_dump(compose, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return mounts


def _inject_metadata_mounts(components, pkg_dir):
    """Add per-honeypot log volume mounts to the metadata addon compose."""
    log_mounts = []
    for hp_name, base in components:
        if base != "honey-pots":
            continue
        logs_json_path = REPO_ROOT / base / hp_name / "deploy" / "logs.json"
        if not logs_json_path.exists():
            continue
        for entry in json.loads(logs_json_path.read_text(encoding="utf-8")):
            log_mounts.append(f"../{hp_name}/{entry['host']}:{entry['container']}:ro")
    if not log_mounts:
        return
    meta_path = pkg_dir / "metadata" / "docker-compose.yml"
    meta_compose = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta_compose["services"]["metadata"].setdefault("volumes", []).extend(log_mounts)
    meta_path.write_text(
        yaml.safe_dump(meta_compose, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _write_vector_config(all_names, pkg_dir):
    """Merge per-component vector.toml files and write the combined config."""
    toml_paths = [pkg_dir / name / "vector" / "vector.toml" for name in all_names]
    sources, sinks = _merge_vector_tomls(toml_paths)
    (pkg_dir / "vector").mkdir(exist_ok=True)
    _write_merged_vector_toml(pkg_dir / "vector" / "vector.toml", sources, sinks)


def _write_root_compose(all_names, vector_mounts, pkg_dir):
    """Write the top-level docker-compose.yml that includes all components and owns the vector service."""
    all_volumes = vector_mounts + [
        "/var/log:/hostlogs:ro",
        "./vector/vector.toml:/etc/vector/vector.toml:ro",
        "vector-data:/vector-data",
    ]
    vol_lines = "\n".join(f"      - {v}" for v in all_volumes)
    inc_lines = "\n".join(f"  - path: {name}/docker-compose.yml" for name in all_names)

    compose_text = (
        "# Generated by honey-net control plane — do not edit on the server.\n"
        "# Source of truth: honey-net.json, honey-pots/<name>/deploy/, addons/<name>/deploy/\n"
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


# ── Public API ────────────────────────────────────────────────────────────────

def assemble_honeypot_package(server, pkg_dir):
    """
    Populates pkg_dir with the honeypot deploy package:
      - <name>/  — each honeypot's and addon's deploy files, vector service stripped
      - vector/vector.toml — merged from all components (sources/sinks deduplicated)
      - docker-compose.yml — include: per component + single merged vector service

    pkg_dir must already exist.  Does NOT generate setup.sh or copy server-config
    files (deploy.py handles those extras for first deploy).
    """
    if yaml is None:
        sys.exit("pyyaml is required — run setup.ps1 or setup.sh to reinstall dependencies")

    components = (
        [(hp, "honey-pots") for hp in server.get("honeypots", [])] +
        [(a,  "addons")     for a  in server.get("addons",    [])]
    )
    all_names = [name for name, _ in components]

    vector_mounts = []
    for name, base in components:
        vector_mounts += _stage_component(name, base, pkg_dir)

    if "metadata" in all_names:
        _inject_metadata_mounts(components, pkg_dir)

    _write_vector_config(all_names, pkg_dir)
    _write_root_compose(all_names, vector_mounts, pkg_dir)
