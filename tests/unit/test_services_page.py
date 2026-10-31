"""Unit tests for the backend services page — offline, operate on fixture state only."""

import sys
from pathlib import Path

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
        assert '<a href="http://100.64.0.2:8000">Malware Catalog</a>' in page
        assert '<a href="http://100.64.0.1:3000">Reporting and Dashboards</a>' in page

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
