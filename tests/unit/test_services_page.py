"""Unit tests for the backend services page — offline, operate on fixture state only."""

import sys
from pathlib import Path
import pytest

# Ensure repo root is on sys.path so scripts.services_page imports correctly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import services_page
from scripts.services_page import render_page, write_page

STATE = {
    "log-stack": {"public_ip": "203.0.113.1", "tailscale_ip": "100.64.0.1"},
    "malware-catalog": {"public_ip": "203.0.113.2", "tailscale_ip": "100.64.0.2"},
}


class TestRenderPage:
    def test_links_catalog_and_grafana(self):
        page = render_page(STATE, "2026-10-31 12:00")
        assert ('<a href="http://100.64.0.2:8000" target="_blank" rel="noopener">'
                "Malware Catalog</a>") in page
        assert ('<a href="http://100.64.0.1:3000" target="_blank" rel="noopener">'
                "Reporting and Dashboards</a>") in page

    def test_missing_ip_renders_no_link(self):
        state = {"log-stack": STATE["log-stack"], "malware-catalog": {"tailscale_ip": None}}
        page = render_page(state, "2026-10-31 12:00")
        assert ":8000" not in page
        assert "no Tailscale IP for malware-catalog" in page
        assert 'href="http://100.64.0.1:3000"' in page

    def test_empty_state_renders_no_links(self):
        assert "<a " not in render_page({}, "2026-10-31 12:00")

    def test_state_values_are_escaped(self):
        page = render_page({"log-stack": {"tailscale_ip": '"><script>'}}, "2026-10-31 12:00")
        assert "<script>" not in page


class TestWritePage:
    def test_writes_lf_only_page_from_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(services_page, "load_state", lambda: STATE)
        out = write_page(tmp_path / "page.html")
        data = out.read_bytes()
        assert b"http://100.64.0.1:3000" in data
        assert b"\r\n" not in data


class TestProvisionWritesPage:
    def _run_provision(self, tmp_path, monkeypatch, provision_one):
        from scripts import provision

        (tmp_path / "state.json").write_text("{}", encoding="utf-8")
        written = []
        monkeypatch.setattr(provision, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(provision, "_STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(provision, "load_manifest",
                            lambda: [{"name": "log-stack", "type": "backend"}])
        monkeypatch.setattr(provision, "_load_ts_api_key", lambda: "key")
        monkeypatch.setattr(provision.getpass, "getpass", lambda _: "password")
        monkeypatch.setattr(provision, "_provision", provision_one)
        monkeypatch.setattr(provision, "write_page",
                            lambda: written.append(True) or tmp_path / "page.html")
        monkeypatch.setattr(sys, "argv", ["provision.py", "--skip-terraform"])
        return provision.main, written

    def test_written_after_success(self, tmp_path, monkeypatch):
        main, written = self._run_provision(tmp_path, monkeypatch, lambda *a, **k: "100.64.0.1")
        main()
        assert written == [True]

    def test_written_when_a_server_fails(self, tmp_path, monkeypatch):
        def fail(*a, **k):
            sys.exit("setup.sh failed")

        main, written = self._run_provision(tmp_path, monkeypatch, fail)
        with pytest.raises(SystemExit):
            main()
        assert written == [True]
