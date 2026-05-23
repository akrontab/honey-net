#!/usr/bin/env python3
"""Run smoke tests for a honeypot type from the control machine."""

import argparse
import runpy
import sys
from pathlib import Path

from lib.config import REPO_ROOT


def main():
    honeypots_dir = REPO_ROOT / "honey-pots"
    available = sorted(
        d.name for d in honeypots_dir.iterdir()
        if d.is_dir() and (d / "test.py").exists()
    )

    if not available:
        sys.exit("No honeypot test.py files found under honey-pots/")

    parser = argparse.ArgumentParser(
        description="Run smoke tests for a honeypot type from the control machine.",
    )
    parser.add_argument(
        "honeypot", nargs="?",
        choices=available,
        metavar="HONEYPOT",
        help=f"Honeypot to test ({', '.join(available)}); omit to choose interactively",
    )
    args = parser.parse_args()

    if args.honeypot:
        name = args.honeypot
    else:
        print("Select a honeypot to test:")
        for i, n in enumerate(available, 1):
            print(f"  [{i}] {n}")
        print()
        choice = input("Enter number: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(available)):
            sys.exit("Invalid selection")
        name = available[int(choice) - 1]

    test_path = honeypots_dir / name / "test.py"
    sys.argv = [str(test_path)]
    runpy.run_path(str(test_path), run_name="__main__")


if __name__ == "__main__":
    main()
