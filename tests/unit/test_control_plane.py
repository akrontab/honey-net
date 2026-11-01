"""Unit tests for the honey.py command table — offline, reads source files only.

honey.py re-execs into the venv on import, so its table is parsed rather than imported.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _command_modules():
    source = (REPO_ROOT / "honey.py").read_text(encoding="utf-8")
    return set(re.findall(r'^\s+\("[a-z-]+",\s*"([a-z_]+)",\s*"', source, re.MULTILINE))


def test_every_script_has_a_command():
    scripts = {p.stem for p in SCRIPTS.glob("*.py")} - {"__init__"}
    assert scripts - _command_modules() == set()


def test_every_command_has_a_script():
    missing = {m for m in _command_modules() if not (SCRIPTS / f"{m}.py").exists()}
    assert missing == set()


def test_every_command_parses_arguments():
    # "--help" must print usage, not run the command.
    no_parser = {
        m for m in _command_modules()
        if "ArgumentParser" not in (SCRIPTS / f"{m}.py").read_text(encoding="utf-8")
    }
    assert no_parser == set()
