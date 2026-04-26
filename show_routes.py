#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0", "requests>=2.28", "rich>=13.0"]
# ///
"""
Demonstrate how different answers lead to different evaluation routes.

Feeds fields one at a time (following the engine's optimal question order)
and shows how the decision path diverges. Non-interactive — runs predefined
scenarios side by side.

Usage:
    uv run show_routes.py construction-all-risks/
    uv run show_routes.py spacecraft-crew-certification/ --url http://localhost:8080
"""

import argparse
import os
import sys
from pathlib import Path

import requests
import yaml
from rich.console import Console
from rich.panel import Panel

console = Console()
DEFAULT_API_URL = "https://api.aethis.ai"

_DECISION_STYLE = {
    "eligible": "bold green",
    "not_eligible": "bold red",
    "undetermined": "bold yellow",
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
        console.print("[red]ERROR:[/red] No test file found")
        sys.exit(1)
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("tests", [])


def discover_bundle(api_url: str, project_name: str) -> str:
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
    console.print(f"[red]ERROR:[/red] No bundle found matching [bold]{project_name}[/bold]")
    sys.exit(1)


def decide(api_url: str, bundle_id: str, field_values: dict) -> dict:
    payload = {
        "bundle_id": bundle_id,
        "field_values": field_values,
        "include_trace": True,
    }
    resp = requests.post(f"{api_url}/api/v1/public/decide", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def walk_scenario(api_url: str, bundle_id: str, all_inputs: dict) -> list:
    """Walk a scenario one field at a time, following the engine's question order.

    Returns a list of steps: [(field_id, value, decision, groups, step_num)]
    """
    field_values: dict = {}
    steps = []

    # Get initial optimal path
    result = decide(api_url, bundle_id, field_values)

    while result["decision"] == "undetermined":
        nq = result.get("next_question")
        if not nq:
            break

        field_id = nq["field_id"]
        if field_id not in all_inputs:
            break  # Scenario doesn't have this field

        value = all_inputs[field_id]
        field_values[field_id] = value
        result = decide(api_url, bundle_id, field_values)

        trace = result.get("trace") or {}
        group_statuses = trace.get("group_statuses") or {}

        steps.append({
            "field_id": field_id,
            "value": value,
            "decision": result["decision"],
            "groups": group_statuses,
            "remaining": len(result.get("optimal_path") or []),
        })

        if result["decision"] != "undetermined":
            break

    return steps


def print_scenario_walk(name: str, steps: list, total_fields: int) -> None:
    """Print the step-by-step walk through a scenario."""
    console.print(f"  [bold]{name}[/bold]")
    console.print()

    for i, step in enumerate(steps):
        field_short = step["field_id"].split(".")[-1]
        value = step["value"]
        decision = step["decision"]
        remaining = step["remaining"]

        # Format value nicely
        if isinstance(value, bool):
            v_str = "[green]true[/green]" if value else "[red]false[/red]"
        elif isinstance(value, str):
            v_str = f"[cyan]{value}[/cyan]"
        else:
            v_str = str(value)

        # Step indicator
        if decision == "undetermined":
            marker = f"[dim]{i + 1}.[/dim]"
            status = f"[dim]({remaining} remaining)[/dim]"
        elif decision == "eligible":
            marker = f"[green]{i + 1}.[/green]"
            status = "[bold green]-> eligible[/bold green]"
        else:
            marker = f"[red]{i + 1}.[/red]"
            status = "[bold red]-> not eligible[/bold red]"

        console.print(f"    {marker} [dim]{field_short}[/dim] = {v_str}  {status}")

        # Show which group failed on decisive steps
        if decision != "undetermined":
            groups = step["groups"]
            failed = [g for g, s in groups.items() if s in ("not_satisfied", "not_satisfied")]
            if failed and decision == "not_eligible":
                console.print(f"       [dim]Failed:[/dim] [red]{', '.join(failed)}[/red]")

    console.print(f"    [dim]Decision in {len(steps)} steps (of {total_fields} fields)[/dim]")
    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Show how different answers lead to different evaluation routes",
    )
    parser.add_argument("example_dir", type=Path, help="Path to example directory")
    parser.add_argument(
        "--url",
        default=os.environ.get("AETHIS_API_URL", DEFAULT_API_URL),
        help=f"API base URL (default: $AETHIS_API_URL or {DEFAULT_API_URL})",
    )
    parser.add_argument("--bundle-id", help="Skip auto-discovery")
    parser.add_argument(
        "--scenarios",
        type=int,
        nargs="*",
        help="Run only these scenario indices (1-based). Default: all.",
    )
    args = parser.parse_args()

    example_dir = args.example_dir.resolve()
    config = load_config(example_dir)
    project_name = config["project"]
    bundle_id = args.bundle_id or discover_bundle(args.url, project_name)
    tests = load_tests(example_dir)

    # Header
    console.print()
    console.print(Panel(
        f"[bold]{project_name}[/bold]\n[dim]{bundle_id}[/dim]",
        title="Route Explorer",
        subtitle=f"[dim]{args.url}[/dim]",
        border_style="cyan",
    ))
    console.print()

    # Get total fields
    initial = decide(args.url, bundle_id, {})
    total_fields = initial.get("fields_evaluated", 0)

    console.print(f"  [dim]{total_fields} fields, {len(tests)} scenarios[/dim]")
    console.print()

    # Walk each scenario
    selected = args.scenarios if args.scenarios else list(range(1, len(tests) + 1))
    for idx in selected:
        if idx < 1 or idx > len(tests):
            continue
        test = tests[idx - 1]
        name = test["name"]
        inputs = test["inputs"]

        steps = walk_scenario(args.url, bundle_id, inputs)
        print_scenario_walk(name, steps, total_fields)

    console.print(f"  [dim]{'─' * 60}[/dim]")
    console.print()


if __name__ == "__main__":
    main()
