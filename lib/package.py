import re
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

from lib.config import REPO_ROOT
from lib.files import copy_tree

# Conf files shipped alongside setup.sh for both provision and reconfigure.
SETUP_CONF_FILES = ["sshd_hardening.conf", "99-hardening.conf", "fail2ban-jail.local"]

# Port reserved for real SSH — never allowed in package.toml.
_RESERVED_PORTS = {65022}


# ── Port collection + validation ─────────────────────────────────────────────

def _load_package_toml(name, base, repo_root=None):
    """Return the parsed package.toml dict for a component, or {} if absent."""
    if tomllib is None:
        sys.exit("Python 3.11+ is required (tomllib). Upgrade Python and re-run setup.")
    root = Path(repo_root) if repo_root else REPO_ROOT
    path = root / base / name / "deploy" / "package.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _compose_host_ports(name, base, repo_root=None):
    """Return the set of host ports declared in a bridge-network component's compose file.

    Returns None if the component uses network_mode: host (exempt from cross-check).
    Returns a set[int] for bridge-network components.
    """
    if yaml is None:
        return None
    root = Path(repo_root) if repo_root else REPO_ROOT
    compose_path = root / base / name / "deploy" / "docker-compose.yml"
    if not compose_path.exists():
        return None
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose.get("services", {}) or {}
    for svc in services.values():
        if isinstance(svc, dict) and svc.get("network_mode") == "host":
            return None  # host-network: exempt from bridge cross-check
    result = set()
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        for port_spec in svc.get("ports", []):
            # Handles "0.0.0.0:3306:3306", "3306:3306", "3306"
            parts = str(port_spec).split(":")
            host_port = int(parts[-2]) if len(parts) >= 2 else int(parts[0])
            result.add(host_port)
    return result


def collect_ports(server, repo_root=None) -> dict:
    """Collect and validate all ports declared by a server's components.

    Returns {port: package_name}.
    Exits with an error on collision, reserved-port, or bridge cross-check failure.
    """
    if tomllib is None:
        sys.exit("Python 3.11+ is required (tomllib). Upgrade Python and re-run setup.")
    components = (
        [(hp, "honey-pots") for hp in server.get("honeypots", [])] +
        [(a,  "addons")     for a  in server.get("addons",    [])]
    )
    port_map = {}
    for name, base in components:
        pkg = _load_package_toml(name, base, repo_root=repo_root)
        declared = [int(p) for p in pkg.get("ports", [])]
        for p in declared:
            if p in _RESERVED_PORTS:
                sys.exit(
                    f"Port error: '{name}' declares reserved port {p} in package.toml "
                    f"(port {p} is used for real SSH)"
                )
            if p in port_map:
                sys.exit(
                    f"Port collision on server '{server['name']}': "
                    f"'{port_map[p]}' and '{name}' both declare port {p}"
                )
            port_map[p] = name
        # Bridge cross-check: for bridge-network components, compose ports: must match package.toml.
        compose_ports = _compose_host_ports(name, base, repo_root=repo_root)
        if compose_ports is not None:
            declared_set = set(declared)
            if declared_set != compose_ports:
                sys.exit(
                    f"Bridge cross-check failed for '{name}' on server '{server['name']}': "
                    f"package.toml declares ports {sorted(declared_set)} but "
                    f"docker-compose.yml declares ports {sorted(compose_ports)}"
                )
    return port_map


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
            mounts.append(vol)  # named volume or absolute path (e.g. ../inbox/foo:/x)
    return mounts


def _merge_vector_tomls(toml_paths):
    """Parse and merge vector.toml files, deduplicating sources/transforms/sinks by key."""
    if tomllib is None:
        sys.exit("Python 3.11+ is required (tomllib). Upgrade Python and re-run setup.")
    sources, transforms, sinks = {}, {}, {}
    for path in toml_paths:
        if not path.exists():
            continue
        with open(path, "rb") as f:
            data = tomllib.load(f)
        for k, v in data.get("sources", {}).items():
            sources.setdefault(k, v)
        for k, v in data.get("transforms", {}).items():
            transforms.setdefault(k, v)
        for k, v in data.get("sinks", {}).items():
            sinks.setdefault(k, v)
    return sources, transforms, sinks


def _toml_scalar(v):
    if isinstance(v, str):
        if "\n" in v:
            # Multi-line literal string — preserves backslashes and quotes verbatim.
            # The opening '''-then-newline is stripped by TOML on parse; we re-emit
            # it the same way so round-trips don't accumulate blank lines.
            return f"'''\n{v.rstrip()}\n'''"
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


def _write_merged_vector_toml(path, sources, transforms, sinks):
    lines = ['data_dir = "/vector-data"', "", "# ── Sources " + "─" * 52]
    for name, fields in sources.items():
        lines += ["", f"[sources.{name}]"]
        _write_toml_block(lines, f"sources.{name}", fields)
    if transforms:
        lines += ["", "", "# ── Transforms " + "─" * 49]
        for name, fields in transforms.items():
            lines += ["", f"[transforms.{name}]"]
            _write_toml_block(lines, f"transforms.{name}", fields)
    lines += ["", "", "# ── Sinks " + "─" * 54]
    for name, fields in sinks.items():
        lines += ["", f"[sinks.{name}]"]
        _write_toml_block(lines, f"sinks.{name}", fields)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


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

    with compose_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(yaml.safe_dump(compose, default_flow_style=False, sort_keys=False))
    return mounts


def _write_vector_config(all_names, pkg_dir):
    """Merge per-component vector.toml files and write the combined config."""
    toml_paths = [pkg_dir / name / "vector" / "vector.toml" for name in all_names]
    sources, transforms, sinks = _merge_vector_tomls(toml_paths)
    (pkg_dir / "vector").mkdir(exist_ok=True)
    _write_merged_vector_toml(pkg_dir / "vector" / "vector.toml", sources, transforms, sinks)


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
    with (pkg_dir / "docker-compose.yml").open("w", encoding="utf-8", newline="\n") as f:
        f.write(compose_text)


# ── Public API ────────────────────────────────────────────────────────────────

def component_build_services(name: str, base: str) -> list[str]:
    """Return Docker service names that have a build: context in the component's compose file."""
    compose_path = REPO_ROOT / base / name / "deploy" / "docker-compose.yml"
    if not compose_path.exists() or yaml is None:
        return []
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    return [
        svc_name
        for svc_name, svc_def in (compose.get("services") or {}).items()
        if isinstance(svc_def, dict) and "build" in svc_def
    ]


def backend_build_services(name: str) -> list[str]:
    """Return Docker service names that have a build: context in a backend server's compose file."""
    compose_path = REPO_ROOT / name / "deploy" / "docker-compose.yml"
    if not compose_path.exists() or yaml is None:
        return []
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    return [
        svc_name
        for svc_name, svc_def in (compose.get("services") or {}).items()
        if isinstance(svc_def, dict) and "build" in svc_def
    ]


def _bash_func_name(component_name):
    """Convert a component name to a valid bash identifier (hyphens → underscores)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", component_name)


def _generate_port_functions(port_map):
    """Return bash source for configure_ports() and reconcile_ports() from a port map."""
    lines = ["# ── Generated by lib/package.py — do not edit on the server ──────────────────", ""]

    # configure_ports: open each declared port
    lines.append("configure_ports() {")
    lines.append('  echo "[ports] Configuring UFW honeypot ports..."')
    for port in sorted(port_map):
        pkg = port_map[port]
        lines.append(f'  ufw allow "{port}/tcp" comment \'{pkg}\'')
    lines.append("}")
    lines.append("")

    # reconcile_ports: prune UFW rules for ports no longer in the declared set
    desired_str = " ".join(str(p) for p in sorted(port_map))
    lines.append("reconcile_ports() {")
    lines.append('  echo "[ports] Reconciling UFW honeypot ports..."')
    lines.append(f'  local _desired=" {desired_str} "')
    lines.append("  while IFS= read -r _line; do")
    lines.append(
        r'    if [[ "$_line" =~ ^([0-9]+)/tcp[[:space:]]+ALLOW[[:space:]]+IN[[:space:]]+Anywhere[[:space:]]*$ ]]; then'
    )
    lines.append('      local _port="${BASH_REMATCH[1]}"')
    lines.append('      if [[ "$_desired" != *" ${_port} "* ]]; then')
    lines.append('        echo "  [ports] Pruning stale rule: ${_port}/tcp"')
    lines.append('        ufw delete allow "${_port}/tcp" || true')
    lines.append("      fi")
    lines.append("    fi")
    lines.append("  done < <(ufw status)")
    lines.append("}")
    return "\n".join(lines)


def _generate_fragment_function(name, base, repo_root=None):
    """Wrap a component's fragment.sh body in a bash function named fragment_<name>().

    Returns the bash function string, or an empty string if no fragment.sh exists.
    """
    root = Path(repo_root) if repo_root else REPO_ROOT
    frag = root / base / name / "deploy" / "setup" / "fragment.sh"
    if not frag.exists():
        return ""
    body = frag.read_text(encoding="utf-8").strip()
    func_name = f"fragment_{_bash_func_name(name)}"
    indented = "\n".join(f"  {line}" if line.strip() else "" for line in body.splitlines())
    return f"{func_name}() {{\n{indented}\n}}"


def _generate_dispatch_tail(components, port_map, repo_root=None):
    """Return the complete generated bash tail for a server.

    Includes configure_ports(), reconcile_ports(), fragment_<name>() functions,
    and the HONEYNET_PHASE case dispatcher.
    """
    lines = [_generate_port_functions(port_map), ""]

    fragment_funcs = []
    for name, base in components:
        fn = _generate_fragment_function(name, base, repo_root=repo_root)
        if fn:
            lines.append(fn)
            lines.append("")
            fragment_funcs.append(f"fragment_{_bash_func_name(name)}")

    # Phase dispatcher
    lines.append("case \"${HONEYNET_PHASE:-firstboot}\" in")
    lines.append("  reconfigure)")
    lines.append("    configure_sshd")
    lines.append("    configure_sysctl")
    lines.append("    configure_fail2ban")
    lines.append("    configure_ports")
    lines.append("    reconcile_ports")
    lines.append("    echo \"[reconfigure] Done.\" ;;")
    lines.append("  firstboot)")
    lines.append("    firstboot_secrets")
    lines.append("    firstboot_apt")
    lines.append("    firstboot_docker")
    lines.append("    ufw_bootstrap")
    lines.append("    configure_sshd")
    lines.append("    sshd_move")
    lines.append("    configure_sysctl")
    lines.append("    configure_fail2ban")
    lines.append("    unattended")
    lines.append("    deploy_files")
    lines.append("    tailscale_join")
    lines.append("    write_env")
    lines.append("    configure_ports")
    for fn in fragment_funcs:
        lines.append(f"    {fn}")
    lines.append("    ;;")
    lines.append("esac")

    return "\n".join(lines) + "\n"


def assemble_honeypot_setup(server, pkg_dir, repo_root=None):
    """Write the assembled setup.sh and conf files for a honeypot server into pkg_dir.

    setup.sh = server-config/setup.sh (function library) + generated dispatch tail.
    Also copies SETUP_CONF_FILES into pkg_dir.

    Used by both provision (alongside the docker package) and reconfigure
    (config-only SCP payload).
    """
    root = Path(repo_root) if repo_root else REPO_ROOT

    # Validate and collect ports first — exits on collision/reserved/bridge mismatch.
    port_map = collect_ports(server, repo_root=repo_root)

    # Read base function library.
    base_sh = root / "server-config" / "setup.sh"
    if not base_sh.exists():
        sys.exit("server-config/setup.sh not found")
    base = base_sh.read_text(encoding="utf-8")

    # Build component list in order (honeypots, then addons).
    components = (
        [(hp, "honey-pots") for hp in server.get("honeypots", [])] +
        [(a,  "addons")     for a  in server.get("addons",    [])]
    )

    tail = _generate_dispatch_tail(components, port_map, repo_root=repo_root)
    assembled = base.rstrip("\n") + "\n\n" + tail

    with (Path(pkg_dir) / "setup.sh").open("w", encoding="utf-8", newline="\n") as f:
        f.write(assembled)

    # Copy conf files.
    for cf in SETUP_CONF_FILES:
        src = root / "server-config" / cf
        if not src.exists():
            sys.exit(f"server-config/{cf} not found")
        (Path(pkg_dir) / cf).write_bytes(src.read_bytes())


def assemble_honeypot_package(server, pkg_dir):
    """
    Populates pkg_dir with the honeypot deploy package:
      - <name>/  — each honeypot's and addon's deploy files, vector service stripped
      - vector/vector.toml — merged from all components (sources/transforms/sinks dedup)
      - docker-compose.yml — include: per component + single merged vector service

    pkg_dir must already exist.  Does NOT generate setup.sh or copy server-config
    files (provision.py handles those extras).

    Per-honeypot sample inbox mounts (../inbox/<honeypot>:/samples) are declared
    by each honeypot's own docker-compose.yml — the assembler does not inject them.
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

    _write_vector_config(all_names, pkg_dir)
    _write_root_compose(all_names, vector_mounts, pkg_dir)
