#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Keep every ``sources/`` directory flat and free of known non-source files.

``aethis generate`` uploads **every file under an example's ``sources/``
directory, recursively**, as authoring input. Anything else kept there - a
retained earlier version of a document, a parity lock, a README about them -
is silently uploaded too and read by the authoring model as if it were law.
Retained versions live in ``<example>/retained/`` and parity files in
``<example>/parity/`` for that reason.

This check fails, naming the path, when any directory called ``sources``
contains:

* a subdirectory (nothing under ``sources/`` may be nested - the upload is
  recursive, so a subdirectory is a second, easily-forgotten set of inputs);
* a file whose name starts with ``PARITY`` or contains ``retained``.

This is a denylist. What it does not establish: that every remaining file in
``sources/`` is a source document, or the right one. A non-source file with
any other name passes. It checks layout and two known names, not content.

Exit 0 when every ``sources/`` directory is clean, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories that are not part of the published tree.
_SKIP = {".git", ".worktrees", "node_modules", ".venv", "__pycache__"}


def _sources_dirs(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("sources")):
        if not path.is_dir():
            continue
        if any(part in _SKIP for part in path.relative_to(root).parts):
            continue
        found.append(path)
    return found


def violations(root: Path = ROOT) -> tuple[list[Path], list[str]]:
    """Return the ``sources/`` directories checked and every violation found."""
    checked = _sources_dirs(root)
    problems: list[str] = []
    for directory in checked:
        for entry in sorted(directory.iterdir()):
            rel = entry.relative_to(root)
            if entry.is_dir():
                problems.append(
                    f"{rel}/: subdirectory under sources/ (authoring uploads it recursively)"
                )
            elif entry.name.startswith("PARITY") or "retained" in entry.name.lower():
                problems.append(
                    f"{rel}: not a source document; move it out of sources/"
                )
    return checked, problems


def main() -> int:
    checked, problems = violations()
    if not checked:
        print(
            "FAIL: found no sources/ directories; refusing to report a clean layout having checked nothing"
        )
        return 1
    if problems:
        print(f"FAIL: {len(problems)} sources/ layout problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nEverything under sources/ is uploaded as authoring input. Keep retained "
            "versions in <example>/retained/ and parity files in <example>/parity/."
        )
        return 1
    print(
        f"PASS: {len(checked)} sources/ directories have no subdirectories or known non-source files (PARITY*, retained)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
