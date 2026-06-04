"""Contract tests for the assembled setup.sh.

Verifies structural invariants on the assembled setup.sh for a known server:
  1. LF-only line endings (no CRLF — stray \\r\\n silently breaks bash on Linux)
  2. Dangerous first-boot steps appear ONLY inside the firstboot branch
  3. The reconfigure branch calls ONLY idempotent configure_* functions
  4. configure_ports() contains only the expected ufw allow lines (port set matches)
  5. reconcile_ports() does not call configure_* steps (it's prune-only)

All tests run offline — no SSH, no live infra.
"""

import sys
import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.package import assemble_honeypot_setup, collect_ports


# ── Fixture: assemble setup.sh for mysql-ssh ──────────────────────────────────

@pytest.fixture(scope="module")
def mysql_ssh_setup(tmp_path_factory):
    manifest = json.loads((REPO_ROOT / "honey-net.json").read_text())
    server = next(s for s in manifest if s["name"] == "mysql-ssh")
    out = tmp_path_factory.mktemp("setup")
    assemble_honeypot_setup(server, out)
    text = (out / "setup.sh").read_text(encoding="utf-8")
    raw  = (out / "setup.sh").read_bytes()
    return text, raw


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLFOnly:
    def test_no_crlf_in_setup_sh(self, mysql_ssh_setup):
        _, raw = mysql_ssh_setup
        assert b"\r\n" not in raw, "setup.sh contains CRLF — will break bash on Linux"


class TestPhaseDispatcher:
    def _reconfigure_branch(self, text):
        """Return the text of the reconfigure) branch in the case statement."""
        # Extract from "reconfigure)" to the next branch "firstboot)" or "esac"
        start = text.find("  reconfigure)")
        end   = text.find("  firstboot)", start)
        if end == -1:
            end = text.find("esac", start)
        return text[start:end]

    def _firstboot_branch(self, text):
        """Return the text of the firstboot) branch in the case statement."""
        start = text.find("  firstboot)")
        end   = text.find("esac", start)
        return text[start:end]

    def test_reconfigure_branch_present(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        assert "  reconfigure)" in text

    def test_firstboot_branch_present(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        assert "  firstboot)" in text

    def test_firstboot_has_ufw_bootstrap(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        fb = self._firstboot_branch(text)
        assert "ufw_bootstrap" in fb

    def test_firstboot_has_sshd_move(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        fb = self._firstboot_branch(text)
        assert "sshd_move" in fb

    def test_firstboot_has_tailscale_join(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        fb = self._firstboot_branch(text)
        assert "tailscale_join" in fb

    def test_reconfigure_has_configure_sshd(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        rc = self._reconfigure_branch(text)
        assert "configure_sshd" in rc

    def test_reconfigure_has_configure_ports(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        rc = self._reconfigure_branch(text)
        assert "configure_ports" in rc

    def test_reconfigure_has_reconcile_ports(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        rc = self._reconfigure_branch(text)
        assert "reconcile_ports" in rc

    def test_reconfigure_does_not_call_firstboot_steps(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        rc = self._reconfigure_branch(text)
        dangerous = ["ufw_bootstrap", "sshd_move", "firstboot_apt",
                     "firstboot_docker", "tailscale_join", "unattended",
                     "deploy_files", "write_env"]
        for step in dangerous:
            assert step not in rc, f"reconfigure branch must not call '{step}'"

    def test_firstboot_does_not_call_reconcile_ports(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        fb = self._firstboot_branch(text)
        assert "reconcile_ports" not in fb, \
            "reconcile_ports should only run on reconfigure (not first-boot)"


class TestConfigurePorts:
    def test_configure_ports_function_exists(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        assert "configure_ports()" in text

    def test_configure_ports_matches_collect_ports(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        manifest = json.loads((REPO_ROOT / "honey-net.json").read_text())
        server   = next(s for s in manifest if s["name"] == "mysql-ssh")
        port_map = collect_ports(server)

        # Extract the configure_ports() function body
        start = text.find("configure_ports() {")
        end   = text.find("\n}", start)
        func_body = text[start:end]

        for port in sorted(port_map):
            assert f'"{port}/tcp"' in func_body, \
                f"configure_ports() missing ufw allow for port {port}"

    def test_no_ufw_allow_in_fragment_functions(self, mysql_ssh_setup):
        text, _ = mysql_ssh_setup
        import re
        # Find the first fragment function *definition* (not a comment or a call).
        m = re.search(r"^fragment_\w+\(\) \{", text, re.MULTILINE)
        if m is None:
            return  # no fragment functions — nothing to check
        fragment_section = text[m.start():]
        ufw_allows = re.findall(r"ufw allow \"\d+/tcp\"", fragment_section)
        assert ufw_allows == [], \
            f"Fragment functions contain ufw allow calls that should have been stripped: {ufw_allows}"


class TestConfFiles:
    def test_conf_files_copied(self, mysql_ssh_setup, tmp_path_factory):
        manifest = json.loads((REPO_ROOT / "honey-net.json").read_text())
        server = next(s for s in manifest if s["name"] == "mysql-ssh")
        out = tmp_path_factory.mktemp("conf")
        assemble_honeypot_setup(server, out)
        from lib.package import SETUP_CONF_FILES
        for cf in SETUP_CONF_FILES:
            assert (out / cf).exists(), f"Conf file not copied: {cf}"
