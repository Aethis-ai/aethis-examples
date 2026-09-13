#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Emit the reviewed, machine-readable scenario inventory for this checkout."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent


def scenario_files() -> list[Path]:
    """Return publishable test files, including nested section scenarios."""
    files = []
    for path in ROOT.rglob("tests/scenarios.yaml"):
        rel = path.relative_to(ROOT)
        if any(part.startswith("_") or part in {"fixtures", "snapshots"} for part in rel.parts):
            continue
        files.append(path)
    return sorted(files)


def build_manifest() -> dict[str, Any]:
    scenarios: list[dict[str, str]] = []
    for scenario_file in scenario_files():
        example_dir = scenario_file.parent.parent
        config = yaml.safe_load((example_dir / "aethis.yaml").read_text())
        pin = config.get("live_ruleset_id")
        if not pin:
            raise ValueError(f"{example_dir}/aethis.yaml has no live_ruleset_id")
        for test in yaml.safe_load(scenario_file.read_text()).get("tests", []):
            scenarios.append(
                {
                    "example_dir": str(example_dir.relative_to(ROOT)),
                    "test_file": str(scenario_file.relative_to(ROOT)),
                    "project": str(config["project"]),
                    "live_ruleset_id": str(pin),
                    "name": str(test["name"]),
                    "field_values": test["inputs"],
                    "expected_outcome": str(test["expect"]["outcome"]),
                    "expectation": test["expect"],
                }
            )
    return {"schema_version": 1, "expected_count": len(scenarios), "scenarios": scenarios}


def manifest_fingerprint(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest["scenarios"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


if __name__ == "__main__":
    print(json.dumps(build_manifest(), indent=2, sort_keys=True))
