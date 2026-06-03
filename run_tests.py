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


def _auth_headers(api_key: str | None) -> dict:
    return {"X-API-Key": api_key} if api_key else {}


def discover_ruleset(api_url: str, project_name: str, api_key: str | None = None) -> str:
    """Find the ruleset_id for a project by matching slug, then section_id."""
    resp = requests.get(f"{api_url}/api/v1/public/rulesets", headers=_auth_headers(api_key), timeout=15)
    resp.raise_for_status()
    rulesets = resp.json()

    if not rulesets:
        console.print("[red]ERROR:[/red] No public rulesets found")
        sys.exit(1)

    # Slugs are the canonical match — a project published under
    # `aethis/<project_name>` resolves cleanly even when the section_id
    # was renamed during authoring.
    for r in rulesets:
        slug = r.get("slug") or ""
        if slug == f"aethis/{project_name}" or slug.endswith(f"/{project_name}"):
            return r["ruleset_id"]

    normalized = project_name.replace("-", "_").lower()

    for r in rulesets:
        section = r["section_id"].replace("-", "_").lower()
        if normalized in section or section in normalized:
            return r["ruleset_id"]

    for r in rulesets:
        if r["section_id"] == project_name:
            return r["ruleset_id"]

    console.print(f"[red]ERROR:[/red] No ruleset found matching project [bold]{project_name}[/bold]")
    for r in rulesets:
        slug = r.get("slug") or "(no slug)"
        console.print(f"  [dim]-[/dim] {r['section_id']} [dim]({r['ruleset_id']}, slug: {slug})[/dim]")
    sys.exit(1)


def run_test(api_url: str, ruleset_id: str, test: dict, *, no_cache: bool = False, api_key: str | None = None) -> dict:
    """Run a single test. Returns the full API response plus pass/fail."""
    payload = {
        "ruleset_id": ruleset_id,
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
            headers=_auth_headers(api_key),
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

    # Fallback: check explanation for source_refs (only when explanation is a
    # list of rule dicts; the public /explain endpoint can return a list of
    # human-readable strings, which we just skip here).
    for r in results:
        explanation = r.get("explanation") or []
        if not isinstance(explanation, list) or not explanation or not isinstance(explanation[0], dict):
            continue
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
        "--ruleset-id",
        help="Skip auto-discovery and use this ruleset_id directly",
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
    parser.add_argument(
        "--api-key",
        default=os.environ.get("AETHIS_API_KEY"),
        help="API key for authenticated access (higher rate limits). Or set AETHIS_API_KEY env var.",
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

    expected_ruleset_id = config.get("live_ruleset_id")
    drift_warning: str | None = None

    if args.ruleset_id:
        ruleset_id = args.ruleset_id
    else:
        discovered = discover_ruleset(args.url, project_name, api_key=args.api_key)
        if expected_ruleset_id and expected_ruleset_id != discovered:
            # Drift tripwire: aethis.yaml's live_ruleset_id pin does not match
            # what the live slug resolves to. Warn loudly but run against the
            # discovered id — the pin may point at a deprecated/deleted ruleset
            # in which case using it would 404 every decide call.
            drift_warning = (
                f"BUNDLE DRIFT: aethis.yaml pins live_ruleset_id={expected_ruleset_id} "
                f"but slug aethis/{project_name} now resolves to {discovered}. "
                f"Running against the live slug; refresh aethis.yaml or republish."
            )
        ruleset_id = discovered
    header.add_row("Ruleset", f"[dim]{ruleset_id}[/dim]")
    console.print(header)
    if drift_warning:
        console.print(f"[bold yellow]⚠ {drift_warning}[/bold yellow]")
    console.print()

    # Run tests
    passed = 0
    failed = 0
    all_results = []
    for test in tests:
        name = test["name"]
        result = run_test(args.url, ruleset_id, test, no_cache=args.no_cache, api_key=args.api_key)
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
