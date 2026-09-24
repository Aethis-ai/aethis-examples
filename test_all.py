#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0", "rich>=13.0"]
# ///
"""
Run every example's test suite in one command.

Discovers each example directory containing tests/scenarios.yaml, runs the
shared run_tests.py against each, and reports a combined pass/fail summary.
Exits non-zero if any example fails — suitable for CI.

Usage:
    uv run test_all.py                       # all examples, against prod
    uv run test_all.py --url http://localhost:8080
    uv run test_all.py spacecraft-crew-certification consumer-credit-prequalification
    uv run test_all.py --verbose             # full per-scenario explanations

Auth: set AETHIS_API_KEY for higher rate limits (the unauthenticated tier
has a usage cap that tight loops can hit). Honoured by run_tests.py via env.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scenario_manifest import build_manifest, manifest_fingerprint


def discover_examples() -> list[Path]:
    """Every publishable scenario directory, recursively and deterministically.

    Skips underscore-prefixed dirs (e.g. _template) — those are scaffolding,
    not publishable examples, and their placeholder scenarios fail by design.
    """
    found = []
    for scenario_file in ROOT.rglob("tests/scenarios.yaml"):
        relative = scenario_file.relative_to(ROOT)
        if any(part.startswith("_") or part in {"fixtures", "snapshots"} for part in relative.parts):
            continue
        found.append(scenario_file.parent.parent)
    return sorted(found, key=lambda p: p.name)


REVIEWED_MANIFEST_SHA256 = "336eec0e68d4431b7e303b5a542da4ecb4bc00b112942eb4069799327c588308"

SUMMARY_COUNTS = frozenset({"expected", "executed", "passed", "failed", "skipped"})
SUMMARY_FIELDS = SUMMARY_COUNTS | {"ruleset_id"}


def complete_suite_summary(payload: object, expected: int, ruleset_id: str) -> dict[str, int]:
    """Validate one child runner's complete result against its selected cases."""
    if not isinstance(payload, dict) or set(payload) != SUMMARY_FIELDS:
        raise ValueError("summary must contain five scenario counts and the immutable ruleset_id")
    if any(type(payload[key]) is not int or payload[key] < 0 for key in SUMMARY_COUNTS):
        raise ValueError("summary counts must be non-negative integers")
    if payload["ruleset_id"] != ruleset_id:
        raise ValueError("summary ruleset_id differs from the selected immutable pin")
    summary = {key: payload[key] for key in SUMMARY_COUNTS}
    if summary["expected"] != expected:
        raise ValueError(f"summary expected {summary['expected']} scenarios, selected set has {expected}")
    if summary["executed"] != expected or summary["passed"] != expected:
        raise ValueError("summary did not execute and pass every selected scenario")
    if summary["failed"] or summary["skipped"]:
        raise ValueError("summary reported failed or skipped scenarios")
    return summary

def verify_manifest(examples: list[Path], manifest: dict) -> None:
    """Fail closed if an eligible scenario vanished from the checked manifest."""
    expected_files = {entry["test_file"] for entry in manifest.get("scenarios", [])}
    found_files = {
        str((example / "tests" / "scenarios.yaml").relative_to(ROOT))
        for example in examples
    }
    if found_files != expected_files:
        raise SystemExit(
            "ERROR: scenario manifest differs from discovered files; regenerate and review "
            f"(manifest={sorted(expected_files)}, discovered={sorted(found_files)})"
        )
    if manifest.get("expected_count") != len(manifest.get("scenarios", [])):
        raise SystemExit("ERROR: scenario manifest expected_count is inconsistent")
    if manifest["expected_count"] < 59:
        raise SystemExit(
            f"ERROR: scenario manifest has {manifest['expected_count']} cases; expected at least 59"
        )
    if manifest_fingerprint(manifest) != REVIEWED_MANIFEST_SHA256:
        raise SystemExit("ERROR: scenario identities differ from the reviewed 59-case manifest")
    nested = [s for s in manifest["scenarios"] if "uk-free-school-meals/sections/" in s["test_file"]]
    if len(nested) != 23:
        raise SystemExit("ERROR: reviewed manifest must contain exactly 23 nested FSM cases")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run every Aethis example test suite against the live API",
    )
    parser.add_argument(
        "examples",
        nargs="*",
        help="Example dir names to run (default: all with tests/scenarios.yaml)",
    )
    parser.add_argument("--url", help="API base URL (passed through to run_tests.py)")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass server caches (passed through to run_tests.py)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full per-scenario output (default: quiet per-example)",
    )
    args = parser.parse_args()

    if args.examples:
        examples = []
        for name in args.examples:
            d = (ROOT / name).resolve()
            if not (d / "tests" / "scenarios.yaml").exists():
                console.print(f"[red]ERROR:[/red] {name} has no tests/scenarios.yaml")
                sys.exit(2)
            examples.append(d)
    else:
        examples = discover_examples()

    if not examples:
        console.print("[red]ERROR:[/red] no examples with tests/scenarios.yaml found")
        sys.exit(2)

    manifest = build_manifest()
    verify_manifest(discover_examples(), manifest)
    selected_files = {str((example / "tests" / "scenarios.yaml").relative_to(ROOT)) for example in examples}
    selected_manifest = [s for s in manifest["scenarios"] if s["test_file"] in selected_files]

    passthrough = []
    if args.url:
        passthrough += ["--url", args.url]
    if args.no_cache:
        passthrough += ["--no-cache"]
    if not args.verbose:
        passthrough += ["-q"]

    results: list[tuple[str, bool]] = []
    summary_errors: list[str] = []
    totals = {"expected": 0, "executed": 0, "passed": 0, "failed": 0, "skipped": 0}
    with tempfile.TemporaryDirectory(prefix="aethis-example-summaries-") as temp_dir:
        for example in examples:
            console.rule(f"[bold]{example.name}[/bold]")
            summary_path = Path(temp_dir) / f"{example.name}.json"
            proc = subprocess.run(
                [
                    "uv",
                    "run",
                    str(ROOT / "run_tests.py"),
                    str(example),
                    *passthrough,
                    "--summary-json",
                    str(summary_path),
                ],
                cwd=ROOT,
                check=False,
            )
            suite_ok = proc.returncode == 0
            scenario_file = str((example / "tests" / "scenarios.yaml").relative_to(ROOT))
            suite_scenarios = [scenario for scenario in selected_manifest if scenario["test_file"] == scenario_file]
            suite_expected = len(suite_scenarios)
            suite_pins = {scenario["live_ruleset_id"] for scenario in suite_scenarios}
            try:
                if len(suite_pins) != 1:
                    raise ValueError("selected scenarios do not share one immutable ruleset pin")
                summary = complete_suite_summary(
                    json.loads(summary_path.read_text()), suite_expected, suite_pins.pop()
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                suite_ok = False
                summary_errors.append(f"{example.name}: {exc}")
            else:
                for key, value in summary.items():
                    totals[key] += value
            results.append((example.name, suite_ok))

    # Combined summary
    console.print()
    table = Table(title="Suite summary", title_style="bold", show_header=True)
    table.add_column("Example")
    table.add_column("Result")
    for name, ok in results:
        table.add_row(name, "[green]PASS[/green]" if ok else "[red]FAIL[/red]")
    console.print(table)

    failed = [name for name, ok in results if not ok]
    expected = len(selected_manifest)
    totals["expected"] = expected
    totals["failed"] += max(0, expected - totals["executed"])
    console.print(
        f"Manifest counts: expected={expected} executed={totals['executed']} "
        f"passed={totals['passed']} failed={totals['failed']} skipped={totals['skipped']}"
    )
    if failed:
        console.print(f"[bold red]{len(failed)}/{len(results)} example suites failed:[/bold red] {', '.join(failed)}")
        for error in summary_errors:
            console.print(f"[red]Invalid child summary:[/red] {error}")
        sys.exit(1)
    console.print(f"[bold green]All {len(results)} example suites passed.[/bold green]")
    sys.exit(0)


if __name__ == "__main__":
    main()
