#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0", "requests>=2.28", "rich>=13.0"]
# ///
"""
Run Aethis example tests against the live API.

Usage:
    uv run run_tests.py spacecraft-crew-certification/
    uv run run_tests.py spacecraft-crew-certification/ --url http://localhost:8080

Without uv:
    pip install pyyaml requests rich
    python run_tests.py spacecraft-crew-certification/
"""

import argparse
import os
import sys
from pathlib import Path

import requests
import yaml
from rich.console import Console
from rich.table import Table

console = Console()
DEFAULT_API_URL = "https://api.aethis.ai"

_DECISION_STYLE = {
    "eligible": "bold green",
    "not_eligible": "bold red",
    "undetermined": "bold yellow",
}

_GROUP_STATUS_LABEL = {
    # New API format
    "satisfied": ("passed", "green"),
    "not_satisfied": ("failed", "red"),
    "pending": ("pending", "yellow"),
    # Legacy API format (backward compat)
}


def load_config(example_dir: Path) -> dict:
    path = example_dir / "aethis.yaml"
    if not path.exists():
        console.print(f"[red]ERROR:[/red] {path} not found")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def load_tests(example_dir: Path) -> list:
    path = example_dir / "tests" / "scenarios.yaml"
    if not path.exists():
        path = example_dir / "tests.yaml"
    if not path.exists():
        console.print("[red]ERROR:[/red] No test file found (tried tests/scenarios.yaml and tests.yaml)")
        sys.exit(1)
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("tests", [])


def discover_bundle(api_url: str, project_name: str) -> str:
    """Find the bundle_id for a project by matching section_id."""
    resp = requests.get(f"{api_url}/api/v1/public/bundles", timeout=15)
    resp.raise_for_status()
    bundles = resp.json()

    if not bundles:
        console.print("[red]ERROR:[/red] No public bundles found")
        sys.exit(1)

    normalized = project_name.replace("-", "_").lower()

    for b in bundles:
        section = b["section_id"].replace("-", "_").lower()
        if normalized in section or section in normalized:
            return b["bundle_id"]

    for b in bundles:
        if b["section_id"] == project_name:
            return b["bundle_id"]

    console.print(f"[red]ERROR:[/red] No bundle found matching project [bold]{project_name}[/bold]")
    for b in bundles:
        console.print(f"  [dim]-[/dim] {b['section_id']} [dim]({b['bundle_id']})[/dim]")
    sys.exit(1)


def run_test(api_url: str, bundle_id: str, test: dict, *, no_cache: bool = False) -> dict:
    """Run a single test. Returns the full API response plus pass/fail."""
    payload = {
        "bundle_id": bundle_id,
        "field_values": test["inputs"],
        "include_explanation": True,
        "include_trace": True,
        "include_timing": True,
        "no_cache": no_cache,
    }
    try:
        resp = requests.post(
            f"{api_url}/api/v1/public/decide",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"error": str(e), "passed": False}

    result = resp.json()
    actual = result["decision"]
    expected = test["expect"]["outcome"]
    result["passed"] = actual == expected
    result["expected"] = expected
    return result


def print_result(name: str, result: dict) -> None:
    """Print a single test result with per-group evaluation status."""
    if "error" in result:
        console.print(f"  [white on red] FAIL [/white on red]  {name}")
        console.print(f"         [dim]API error: {result['error']}[/dim]")
        console.print()
        return

    actual = result["decision"]
    expected = result["expected"]
    passed = result["passed"]
    style = _DECISION_STYLE.get(actual, "")

    badge = "[black on green] PASS [/black on green]" if passed else "[white on red] FAIL [/white on red]"
    console.print(f"  {badge}  [bold]{name}[/bold]")

    # Decision + fields
    provided = result.get("fields_provided", 0)
    evaluated = result.get("fields_evaluated", 0)
    console.print(f"         [{style}]{actual}[/{style}] [dim]({provided}/{evaluated} fields provided)[/dim]")

    if not passed:
        console.print(f"         [dim]expected[/dim] [bold]{expected}[/bold] [dim]but got[/dim] [{style}]{actual}[/{style}]")

    # Per-group evaluation status from trace (much more informative than listing all rules)
    trace = result.get("trace") or {}
    group_statuses = trace.get("group_statuses") or {}
    if group_statuses:
        parts = []
        for group, status in group_statuses.items():
            label, color = _GROUP_STATUS_LABEL.get(status, (status.lower(), "dim"))
            parts.append(f"[{color}]{group}: {label}[/{color}]")
        console.print(f"         {' '.join(parts)}")

    # Undetermined: next question + optimal path
    if actual == "undetermined":
        nq = result.get("next_question")
        if nq:
            console.print(f"         [yellow]Next question:[/yellow] {nq['question']} [dim]({nq['field_id']})[/dim]")

        path = result.get("optimal_path")
        if path:
            remaining = [f"[dim]{p['field_id']}[/dim]" for p in path]
            console.print(f"         [yellow]Optimal path[/yellow] ({len(path)} remaining): {' [dim]->[/dim] '.join(remaining)}")

    # Missing fields for failures
    if not passed:
        missing = result.get("missing_fields")
        if missing:
            console.print(f"         [dim]Missing:[/dim] {', '.join(missing)}")

    # Timing
    timing = result.get("timing")
    if timing:
        total = timing.get("total_ms", 0)
        if timing.get("cache_hit"):
            console.print(f"         [dim]Timing:[/dim] [green]{total:.1f}ms[/green] [dim](CACHE HIT)[/dim]")
        else:
            parts = []
            compile_ms = timing.get("compilation_ms") or timing.get("compilation_ms")
            eval_ms = timing.get("evaluation_ms")
            if compile_ms is not None:
                parts.append(f"compile {compile_ms:.1f}ms")
            if eval_ms is not None:
                parts.append(f"eval {eval_ms:.1f}ms")
            detail = f" [dim]({', '.join(parts)})[/dim]" if parts else ""
            console.print(f"         [dim]Timing:[/dim] {total:.1f}ms{detail}")

    console.print()


def print_provenance(results: list) -> None:
    """Print provenance summary — inverted: source passages → rules that cite them."""
    # Collect provenance from the first result that has trace data
    for r in results:
        trace = r.get("trace") or {}
        provenance = trace.get("provenance") or {}
        if not provenance:
            continue

        # Invert: group by source passage, list which rules cite it
        # Key = (section_path, quote_preview), Value = list of rule names
        passage_to_rules: dict[str, dict] = {}
        for criterion_id, prov in provenance.items():
            for anchor in prov.get("anchors") or []:
                section = anchor.get("section_path", "")
                doc_id = anchor.get("doc_id", "")
                quote = anchor.get("quote", "")
                preview = quote.replace("\n", " ").strip()
                if len(preview) > 140:
                    preview = preview[:137] + "..."

                key = section or doc_id
                if key not in passage_to_rules:
                    passage_to_rules[key] = {"doc_id": doc_id, "preview": preview, "rules": []}
                if criterion_id not in passage_to_rules[key]["rules"]:
                    passage_to_rules[key]["rules"].append(criterion_id)

        if not passage_to_rules:
            continue

        console.print(f"  [bold]Provenance[/bold] [dim](source passages → rules)[/dim]")
        console.print()
        for section_path, info in passage_to_rules.items():
            rules_str = ", ".join(info["rules"])
            console.print(f"    [cyan]{section_path}[/cyan]")
            if info["preview"]:
                console.print(f"      [italic dim]\"{info['preview']}\"[/italic dim]")
            console.print(f"      [dim]Rules:[/dim] {rules_str}")
            console.print()
        return

    # Fallback: check explanation for source_refs
    for r in results:
        explanation = r.get("explanation") or []
        has_refs = any(rule.get("source_refs") for rule in explanation)
        if has_refs:
            console.print(f"  [bold]Provenance[/bold] [dim](source references per rule)[/dim]")
            console.print()
            for rule in explanation:
                refs = rule.get("source_refs")
                if refs:
                    console.print(f"    [cyan]{rule.get('title', rule.get('criterion_id'))}[/cyan]")
                    console.print(f"      [dim]{', '.join(refs)}[/dim]")
            console.print()
            return


def main():
    parser = argparse.ArgumentParser(
        description="Run Aethis example tests against the live API",
    )
    parser.add_argument("example_dir", type=Path, help="Path to example directory")
    parser.add_argument(
        "--url",
        default=os.environ.get("AETHIS_API_URL", DEFAULT_API_URL),
        help=f"API base URL (default: $AETHIS_API_URL or {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--bundle-id",
        help="Skip auto-discovery and use this bundle_id directly",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output (pass/fail only, no explanations)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass server caches to measure uncached performance",
    )
    args = parser.parse_args()

    example_dir = args.example_dir.resolve()
    if not example_dir.is_dir():
        console.print(f"[red]ERROR:[/red] {example_dir} is not a directory")
        sys.exit(1)

    config = load_config(example_dir)
    project_name = config["project"]
    tests = load_tests(example_dir)

    # Header
    console.print()
    header = Table(show_header=False, box=None, padding=(0, 1))
    header.add_column(style="dim", width=8)
    header.add_column()
    header.add_row("Project", f"[bold]{project_name}[/bold]")
    header.add_row("API", f"[dim]{args.url}[/dim]")
    header.add_row("Tests", str(len(tests)))

    if args.bundle_id:
        bundle_id = args.bundle_id
    else:
        bundle_id = discover_bundle(args.url, project_name)
    header.add_row("Bundle", f"[dim]{bundle_id}[/dim]")
    console.print(header)
    console.print()

    # Run tests
    passed = 0
    failed = 0
    all_results = []
    for test in tests:
        name = test["name"]
        result = run_test(args.url, bundle_id, test, no_cache=args.no_cache)
        all_results.append(result)

        if result.get("passed"):
            passed += 1
        else:
            failed += 1

        if args.quiet:
            if result.get("passed"):
                console.print(f"  [green]PASS[/green]  {name}")
            else:
                console.print(f"  [red]FAIL[/red]  {name}")
        else:
            print_result(name, result)

    # Provenance summary (once, after all tests)
    if not args.quiet:
        print_provenance(all_results)

    # Summary
    total = passed + failed
    console.print(f"  [dim]{'─' * 60}[/dim]")
    if failed == 0:
        console.print(f"  [bold green]All {total} tests passed.[/bold green]")
    else:
        console.print(f"  [bold red]{failed}/{total} tests failed.[/bold red]")
    console.print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
