#!/usr/bin/env python3
"""Generate backend-services.html: a local page linking to the backend web services.

Links are built from the Tailscale IPs in state.json, so the page is gitignored and
only resolves from a machine on the tailnet. provision.py writes it after server
setup; re-run this command when IPs change (e.g. after sync or deprovision).
"""

import argparse
import html
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.color import green
from lib.config import REPO_ROOT, load_state

PAGE_FILE = REPO_ROOT / "backend-services.html"

# (title, description, server name in state.json, port published in the server's compose file)
SERVICES = [
    ("Malware Catalog", "Captured samples and enrichment results.", "malware-catalog", 8000),
    ("Reporting and Dashboards", "Grafana dashboards and log search.", "log-stack", 3000),
]

_CSS = """\
:root { color-scheme: light dark; --bg: #f6f7f8; --card: #fff; --text: #1c2024; --muted: #60666d; --line: #dcdfe3; --link: #0b63ce; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #15181b; --card: #1e2226; --text: #eceef0; --muted: #a0a6ac; --line: #32383e; --link: #70b0ff; }
}
body { margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--text); font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 40rem; margin: 0 auto; }
h1 { margin: 0 0 1.5rem; font-size: 1.5rem; }
section { margin-bottom: 1rem; padding: 1rem 1.25rem; background: var(--card); border: 1px solid var(--line); border-radius: 8px; }
h2 { margin: 0; font-size: 1.1rem; }
a { color: var(--link); }
p { margin: .25rem 0 0; }
.muted { color: var(--muted); font-size: .875rem; }
"""


def _render_service(title, description, server, port, state):
    title_html = html.escape(title)
    ts_ip = state.get(server, {}).get("tailscale_ip")
    if ts_ip:
        url = html.escape(f"http://{ts_ip}:{port}", quote=True)
        heading = f'<a href="{url}">{title_html}</a>'
        location = url
    else:
        heading = title_html
        location = f"Unavailable: no Tailscale IP for {html.escape(server)} in state.json"
    return (
        "<section>\n"
        f"<h2>{heading}</h2>\n"
        f"<p>{html.escape(description)}</p>\n"
        f'<p class="muted">{location}</p>\n'
        "</section>\n"
    )


def render_page(state, generated_at):
    sections = "".join(
        _render_service(title, description, server, port, state)
        for title, description, server, port in SERVICES
    )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Honey-Net Services</title>\n"
        f"<style>\n{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        "<h1>Honey-Net Services</h1>\n"
        f"{sections}"
        f'<p class="muted">Requires Tailscale. Generated {html.escape(generated_at)}.</p>\n'
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def write_page(path=PAGE_FILE):
    """Render the page from state.json and write it; return its absolute path."""
    page = render_page(load_state(), datetime.now().strftime("%Y-%m-%d %H:%M"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    return Path(path).resolve()


def main():
    argparse.ArgumentParser(
        description="Regenerate backend-services.html from state.json.",
    ).parse_args()
    print(green(f"Backend services page: {write_page().as_uri()}"))


if __name__ == "__main__":
    main()
