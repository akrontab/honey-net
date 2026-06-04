"""Unit tests for collect_ports — collision, reserved-port, bridge cross-check, union.

All tests are offline: they operate on temporary fixture directories, no SSH, no
docker, no live state.json.  Any test that opens a socket or calls subprocess
belongs in a higher tier.
"""

import sys
from pathlib import Path
import pytest

# Ensure repo root is on sys.path so lib.package imports correctly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.package import collect_ports


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _write_toml(root, base, name, ports):
    d = root / base / name / "deploy"
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.toml").write_text(f"ports = {ports!r}\n", encoding="utf-8")


def _write_bridge_compose(root, base, name, ports):
    """Write a minimal bridge-network docker-compose.yml with the given host ports."""
    d = root / base / name / "deploy"
    d.mkdir(parents=True, exist_ok=True)
    port_lines = "\n".join(f'      - "0.0.0.0:{p}:{p}"' for p in ports)
    compose = (
        "services:\n"
        f"  {name}:\n"
        "    image: scratch\n"
        "    ports:\n"
        f"{port_lines}\n"
        "    networks:\n"
        "      - honeypot\n"
        "networks:\n"
        "  honeypot:\n"
        "    driver: bridge\n"
    )
    (d / "docker-compose.yml").write_text(compose, encoding="utf-8")


def _write_host_compose(root, base, name):
    """Write a minimal host-network docker-compose.yml (no ports:)."""
    d = root / base / name / "deploy"
    d.mkdir(parents=True, exist_ok=True)
    compose = (
        "services:\n"
        f"  {name}:\n"
        "    image: scratch\n"
        "    network_mode: host\n"
    )
    (d / "docker-compose.yml").write_text(compose, encoding="utf-8")


def _server(name, honeypots=None, addons=None):
    return {"name": name, "type": "honeypot",
            "honeypots": honeypots or [], "addons": addons or []}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestUnion:
    def test_no_components_returns_empty(self, tmp_path):
        s = _server("empty")
        assert collect_ports(s, repo_root=tmp_path) == {}

    def test_single_component_single_port(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "foo", [8080])
        s = _server("test", honeypots=["foo"])
        assert collect_ports(s, repo_root=tmp_path) == {8080: "foo"}

    def test_union_across_components(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "foo", [8080])
        _write_toml(tmp_path, "honey-pots", "bar", [8081])
        s = _server("test", honeypots=["foo", "bar"])
        result = collect_ports(s, repo_root=tmp_path)
        assert result == {8080: "foo", 8081: "bar"}

    def test_component_with_no_package_toml_contributes_no_ports(self, tmp_path):
        # bar has no package.toml — its deploy dir doesn't even exist — should be skipped.
        _write_toml(tmp_path, "honey-pots", "foo", [8080])
        s = _server("test", honeypots=["foo", "bar"])
        result = collect_ports(s, repo_root=tmp_path)
        assert result == {8080: "foo"}

    def test_addons_ports_merged(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "foo", [22])
        _write_toml(tmp_path, "addons", "my-addon", [9999])
        s = _server("test", honeypots=["foo"], addons=["my-addon"])
        result = collect_ports(s, repo_root=tmp_path)
        assert result == {22: "foo", 9999: "my-addon"}

    def test_component_owner_is_correct(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "alpha", [22, 23])
        _write_toml(tmp_path, "honey-pots", "beta", [3306])
        s = _server("test", honeypots=["alpha", "beta"])
        result = collect_ports(s, repo_root=tmp_path)
        assert result[22] == "alpha"
        assert result[23] == "alpha"
        assert result[3306] == "beta"


class TestCollision:
    def test_two_components_same_port_exits(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "cowrie", [22])
        _write_toml(tmp_path, "honey-pots", "rival", [22])
        s = _server("test", honeypots=["cowrie", "rival"])
        with pytest.raises(SystemExit) as exc:
            collect_ports(s, repo_root=tmp_path)
        assert "22" in str(exc.value)
        assert "cowrie" in str(exc.value)
        assert "rival" in str(exc.value)

    def test_collision_message_names_server(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "a", [80])
        _write_toml(tmp_path, "honey-pots", "b", [80])
        s = _server("my-server", honeypots=["a", "b"])
        with pytest.raises(SystemExit) as exc:
            collect_ports(s, repo_root=tmp_path)
        assert "my-server" in str(exc.value)


class TestReservedPorts:
    def test_port_65022_is_rejected(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "bad", [65022])
        s = _server("test", honeypots=["bad"])
        with pytest.raises(SystemExit) as exc:
            collect_ports(s, repo_root=tmp_path)
        assert "65022" in str(exc.value)

    def test_regular_port_is_accepted(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "good", [22])
        s = _server("test", honeypots=["good"])
        assert collect_ports(s, repo_root=tmp_path) == {22: "good"}


class TestBridgeCrossCheck:
    def test_matching_ports_pass(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "svc", [3306])
        _write_bridge_compose(tmp_path, "honey-pots", "svc", [3306])
        s = _server("test", honeypots=["svc"])
        assert collect_ports(s, repo_root=tmp_path) == {3306: "svc"}

    def test_mismatch_exits(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "svc", [3306])
        _write_bridge_compose(tmp_path, "honey-pots", "svc", [5432])
        s = _server("test", honeypots=["svc"])
        with pytest.raises(SystemExit) as exc:
            collect_ports(s, repo_root=tmp_path)
        assert "cross-check" in str(exc.value).lower() or "3306" in str(exc.value)

    def test_host_network_is_exempt(self, tmp_path):
        # Host-network components have no compose ports: — package.toml is sole source.
        _write_toml(tmp_path, "honey-pots", "cowrie", [22, 23])
        _write_host_compose(tmp_path, "honey-pots", "cowrie")
        s = _server("test", honeypots=["cowrie"])
        result = collect_ports(s, repo_root=tmp_path)
        assert result == {22: "cowrie", 23: "cowrie"}

    def test_no_compose_file_is_exempt(self, tmp_path):
        # Addons with no compose file at all are treated as exempt.
        _write_toml(tmp_path, "addons", "meta", [])
        s = _server("test", addons=["meta"])
        assert collect_ports(s, repo_root=tmp_path) == {}

    def test_extra_compose_port_not_in_toml_exits(self, tmp_path):
        _write_toml(tmp_path, "honey-pots", "svc", [80])
        _write_bridge_compose(tmp_path, "honey-pots", "svc", [80, 443])
        s = _server("test", honeypots=["svc"])
        with pytest.raises(SystemExit):
            collect_ports(s, repo_root=tmp_path)


class TestRealPackages:
    """Smoke-check the real packages in the repo against the live honey-net.json."""

    def test_mysql_ssh_ports_valid(self):
        """mysql-ssh server (cowrie + http + mysql + addons) passes all validation."""
        import json
        manifest = json.loads((REPO_ROOT / "honey-net.json").read_text())
        server = next(s for s in manifest if s["name"] == "mysql-ssh")
        result = collect_ports(server)
        assert 22 in result   # cowrie
        assert 23 in result   # cowrie
        assert 80 in result   # http
        assert 443 in result  # http
        assert 3306 in result # mysql

    def test_smb_ftp_ports_valid(self):
        """smb-ftp server (ftp + smb + addons) passes all validation."""
        import json
        manifest = json.loads((REPO_ROOT / "honey-net.json").read_text())
        server = next(s for s in manifest if s["name"] == "smb-ftp")
        result = collect_ports(server)
        assert 21 in result   # ftp
        assert 139 in result  # smb
        assert 445 in result  # smb
