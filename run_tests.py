#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0", "requests>=2.28", "rich>=13.0", "rfc8785==0.1.4"]
# ///
"""
Run Aethis example tests against the live API.

Usage:
    uv run run_tests.py spacecraft-crew-certification/
    uv run run_tests.py spacecraft-crew-certification/ --url http://localhost:8080

Dependencies (pyyaml, requests, rich) are resolved automatically by `uv run`.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml
from rich.console import Console
from rich.table import Table

from input_identity import decision_input_hash, needs_numeric_schema

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


def load_tests(example_dir: Path) -> list[dict[str, Any]]:
    path = example_dir / "tests" / "scenarios.yaml"
    if not path.exists():
        path = example_dir / "tests.yaml"
    if not path.exists():
        console.print("[red]ERROR:[/red] No test file found (tried tests/scenarios.yaml and tests.yaml)")
        sys.exit(1)
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not isinstance(data.get("tests"), list) or not data["tests"]:
        raise ValueError(f"{path} must contain a non-empty tests list")
    for test in data["tests"]:
        if not isinstance(test, dict) or not isinstance(test.get("name"), str) or not isinstance(test.get("inputs"), dict):
            raise TypeError(f"{path} has malformed test case")
        outcome = test.get("expect", {}).get("outcome") if isinstance(test.get("expect"), dict) else None
        if outcome not in _DECISION_STYLE:
            raise ValueError(f"{path} has invalid expected outcome {outcome!r}")
    return data["tests"]


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


def _retry_delay(response: requests.Response) -> float:
    """Return a bounded, server-directed delay for a throttled request."""
    try:
        return max(0.0, min(float(response.headers.get("Retry-After", "0")), 5.0))
    except ValueError:
        return 0.0


def _has_expected_field_error(result: dict[str, Any], expected: str) -> bool:
    field_errors = result.get("field_errors") or {}
    if isinstance(field_errors, dict):
        return any(expected in str(value) for value in field_errors.values())
    return expected in str(field_errors)


def run_test(
    api_url: str,
    ruleset_id: str,
    test: dict[str, Any],
    *,
    no_cache: bool = False,
    api_key: str | None = None,
    rich: bool = False,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Run a single test. Returns the full API response plus pass/fail."""
    payload = {
        "ruleset_id": ruleset_id,
        "field_values": test["inputs"],
        # These are weighted API features. Keep the no-key default lean enough
        # for the documented five-case quickstart; rich evidence is opt-in.
        "include_explanation": rich,
        "include_trace": rich,
        "include_timing": rich,
        "no_cache": no_cache,
    }
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                f"{api_url}/api/v1/public/decide",
                json=payload,
                headers=_auth_headers(api_key),
                timeout=30,
            )
        except requests.RequestException as exc:
            return {"error": str(exc), "passed": False}
        if resp.status_code != 429:
            try:
                resp.raise_for_status()
            except requests.RequestException as exc:
                return {"error": str(exc), "passed": False}
            break
        if attempt == max_retries:
            return {
                "error": f"rate limited after {max_retries + 1} attempts",
                "passed": False,
                "rate_limited": True,
            }
        time.sleep(_retry_delay(resp))

    result = resp.json()
    actual = result.get("decision")
    expected = test["expect"]["outcome"]
    expected_error = test["expect"].get("field_error")
    blocking_errors = result.get("field_errors") or {}
    if expected_error:
        result["passed"] = expected == actual == "undetermined" and _has_expected_field_error(result, expected_error)
    else:
        result["passed"] = actual == expected and not blocking_errors
        if blocking_errors:
            result["error"] = "response carried blocking field_errors"
    if result.get("ruleset_id") != ruleset_id:
        result["passed"] = False
        result["error"] = "response ruleset identity differs from the requested immutable pin"
    schema = None
    try:
        if needs_numeric_schema(test["inputs"]):
            schema_response = requests.get(
                f"{api_url}/api/v1/public/rulesets/{ruleset_id}/schema",
                headers=_auth_headers(api_key),
                timeout=30,
            )
            schema_response.raise_for_status()
            schema = schema_response.json()
        expected_hash = decision_input_hash(test["inputs"], result, schema)
    except (requests.RequestException, ValueError, TypeError) as exc:
        result["passed"] = False
        result["error"] = f"input identity could not be verified: {type(exc).__name__}"
        return result
    if result.get("inputs_hash") != expected_hash:
        result["passed"] = False
        result["error"] = "response input identity differs from the submitted fields"
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

        console.print("  [bold]Provenance[/bold] [dim](source passages → rules)[/dim]")
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
            console.print("  [bold]Provenance[/bold] [dim](source references per rule)[/dim]")
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
    parser.add_argument(
        "--rich",
        action="store_true",
        help="Request explanation, trace and timing (higher weighted API cost).",
    )
    parser.add_argument(
        "--max-retries",
        default=2,
        type=int,
        help="Bounded retries for HTTP 429 responses (default: 2).",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        help="Write machine-readable expected/executed/passed/failed/skipped counts.",
    )
    args = parser.parse_args()
    if args.max_retries < 0:
        parser.error("--max-retries must be zero or greater")

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
    if not expected_ruleset_id and not args.ruleset_id:
        console.print("[red]ERROR:[/red] aethis.yaml must pin live_ruleset_id")
        sys.exit(1)

    if args.ruleset_id:
        if args.ruleset_id != expected_ruleset_id:
            parser.error("--ruleset-id must match the reviewed live_ruleset_id pin")
        ruleset_id = args.ruleset_id
    else:
        discovered = discover_ruleset(args.url, project_name, api_key=args.api_key)
        if expected_ruleset_id != discovered:
            console.print(
                "[bold red]ERROR: BUNDLE DRIFT:[/bold red] "
                f"aethis.yaml pins live_ruleset_id={expected_ruleset_id} but "
                f"slug aethis/{project_name} resolves to {discovered}. Refusing to test a different artefact."
            )
            sys.exit(1)
        ruleset_id = discovered
    header.add_row("Ruleset", f"[dim]{ruleset_id}[/dim]")
    console.print(header)
    console.print()

    # Run tests
    passed = 0
    failed = 0
    all_results = []
    for test in tests:
        name = test["name"]
        result = run_test(
            args.url,
            ruleset_id,
            test,
            no_cache=args.no_cache,
            api_key=args.api_key,
            rich=args.rich,
            max_retries=args.max_retries,
        )
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
    console.print(
        f"  [dim]Counts:[/dim] expected={len(tests)} executed={total} "
        f"passed={passed} failed={failed} skipped=0"
    )
    if args.summary_json:
        args.summary_json.write_text(
            json.dumps(
                {
                    "expected": len(tests),
                    "executed": total,
                    "passed": passed,
                    "failed": failed,
                    "skipped": 0,
                    "ruleset_id": ruleset_id,
                }
            )
            + "\n"
        )
    console.print(f"  [dim]{'─' * 60}[/dim]")
    if failed == 0:
        console.print(f"  [bold green]All {total} tests passed.[/bold green]")
    else:
        console.print(f"  [bold red]{failed}/{total} tests failed.[/bold red]")
    console.print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
