#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13.0"]
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
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()
ROOT = Path(__file__).resolve().parent


def discover_examples() -> list[Path]:
    """Every example dir with a tests/scenarios.yaml, sorted.

    Skips underscore-prefixed dirs (e.g. _template) — those are scaffolding,
    not publishable examples, and their placeholder scenarios fail by design.
    """
    found = [
        p.parent.parent
        for p in ROOT.glob("*/tests/scenarios.yaml")
        if not p.parent.parent.name.startswith("_")
    ]
    return sorted(found, key=lambda p: p.name)


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

    passthrough = []
    if args.url:
        passthrough += ["--url", args.url]
    if args.no_cache:
        passthrough += ["--no-cache"]
    if not args.verbose:
        passthrough += ["-q"]

    results: list[tuple[str, bool]] = []
    for example in examples:
        console.rule(f"[bold]{example.name}[/bold]")
        proc = subprocess.run(
            ["uv", "run", str(ROOT / "run_tests.py"), str(example), *passthrough],
            cwd=ROOT,
        )
        results.append((example.name, proc.returncode == 0))

    # Combined summary
    console.print()
    table = Table(title="Suite summary", title_style="bold", show_header=True)
    table.add_column("Example")
    table.add_column("Result")
    for name, ok in results:
        table.add_row(name, "[green]PASS[/green]" if ok else "[red]FAIL[/red]")
    console.print(table)

    failed = [name for name, ok in results if not ok]
    if failed:
        console.print(f"[bold red]{len(failed)}/{len(results)} example suites failed:[/bold red] {', '.join(failed)}")
        sys.exit(1)
    console.print(f"[bold green]All {len(results)} example suites passed.[/bold green]")
    sys.exit(0)


if __name__ == "__main__":
    main()
