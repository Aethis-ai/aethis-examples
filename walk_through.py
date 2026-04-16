#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0", "requests>=2.28", "rich>=13.0"]
# ///
"""
Interactive eligibility walk-through — answer one question at a time.

Demonstrates how the eligibility engine picks the optimal next question
and short-circuits as soon as a decision is reached.

Usage:
    uv run walk_through.py construction-all-risks/
    uv run walk_through.py spacecraft-crew-certification/ --url http://localhost:8080
"""

import argparse
import os
import sys
from pathlib import Path

import requests
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()
DEFAULT_API_URL = "https://api.aethis.ai"

_DECISION_STYLE = {
    "eligible": "bold green",
    "not_eligible": "bold red",
    "undetermined": "bold yellow",
}

_GROUP_STATUS_LABEL = {
    "satisfied": ("passed", "green"),
    "not_satisfied": ("failed", "red"),
    "pending": ("pending", "yellow"),
}


def load_config(example_dir: Path) -> dict:
    path = example_dir / "aethis.yaml"
    if not path.exists():
        console.print(f"[red]ERROR:[/red] {path} not found")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


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


def get_schema(api_url: str, bundle_id: str) -> dict:
    resp = requests.get(f"{api_url}/api/v1/public/bundles/{bundle_id}/schema", timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return {f["field_id"]: f for f in data.get("fields", [])}


def decide(api_url: str, bundle_id: str, field_values: dict) -> dict:
    payload = {
        "bundle_id": bundle_id,
        "field_values": field_values,
        "include_trace": True,
    }
    resp = requests.post(f"{api_url}/api/v1/public/decide", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def prompt_for_value(field_id: str, field_info: dict) -> object:
    """Prompt the user for a field value with type-aware input."""
    field_type = field_info.get("field_type", "string")
    enum_values = field_info.get("enum_values")

    if field_type == "boolean":
        while True:
            raw = Prompt.ask(
                f"  [dim]>[/dim]",
                choices=["true", "false", "t", "f", "yes", "no", "y", "n"],
                show_choices=False,
            ).lower()
            if raw in ("true", "t", "yes", "y"):
                return True
            return False

    elif field_type == "enum" and enum_values:
        console.print(f"    [dim]Options: {', '.join(enum_values)}[/dim]")
        while True:
            raw = Prompt.ask(f"  [dim]>[/dim]")
            if raw in enum_values:
                return raw
            console.print(f"    [red]Must be one of: {', '.join(enum_values)}[/red]")

    elif field_type == "integer":
        while True:
            raw = Prompt.ask(f"  [dim]>[/dim]")
            try:
                return int(raw)
            except ValueError:
                console.print(f"    [red]Enter a number[/red]")

    else:
        return Prompt.ask(f"  [dim]>[/dim]")


def print_status(result: dict, step: int, total_fields: int) -> None:
    """Print current evaluation status after each answer."""
    decision = result["decision"]
    style = _DECISION_STYLE.get(decision, "")
    provided = result.get("fields_provided", 0)

    console.print(f"    [{style}]{decision}[/{style}] [dim]({provided}/{total_fields} fields answered)[/dim]")

    # Show group statuses
    trace = result.get("trace") or {}
    group_statuses = trace.get("group_statuses") or {}
    if group_statuses:
        parts = []
        for group, status in group_statuses.items():
            label, color = _GROUP_STATUS_LABEL.get(status, (status.lower(), "dim"))
            parts.append(f"[{color}]{group}: {label}[/{color}]")
        console.print(f"    {' '.join(parts)}")


def main():
    parser = argparse.ArgumentParser(
        description="Interactive eligibility walk-through — answer questions one at a time",
    )
    parser.add_argument("example_dir", type=Path, help="Path to example directory")
    parser.add_argument(
        "--url",
        default=os.environ.get("AETHIS_API_URL", DEFAULT_API_URL),
        help=f"API base URL (default: $AETHIS_API_URL or {DEFAULT_API_URL})",
    )
    parser.add_argument("--bundle-id", help="Skip auto-discovery")
    args = parser.parse_args()

    example_dir = args.example_dir.resolve()
    config = load_config(example_dir)
    project_name = config["project"]
    bundle_id = args.bundle_id or discover_bundle(args.url, project_name)

    # Load field schema for type-aware prompts
    schema = get_schema(args.url, bundle_id)

    # Header
    console.print()
    console.print(Panel(
        f"[bold]{project_name}[/bold]\n[dim]{bundle_id}[/dim]",
        title="Interactive Walk-Through",
        subtitle=f"[dim]{args.url}[/dim]",
        border_style="cyan",
    ))
    console.print()

    # Initial call with no fields to get the optimal path
    field_values: dict = {}
    result = decide(args.url, bundle_id, field_values)
    total_fields = result.get("fields_evaluated", 0)

    path = result.get("optimal_path") or []
    if path:
        console.print(f"  [dim]The engine has planned an optimal path of {len(path)} questions.[/dim]")
        console.print()

    step = 0
    while result["decision"] == "undetermined":
        nq = result.get("next_question")
        if not nq:
            console.print("  [yellow]No more questions but decision is undetermined.[/yellow]")
            break

        step += 1
        field_id = nq["field_id"]
        question = nq["question"]
        field_info = schema.get(field_id, {})
        field_type = field_info.get("field_type", "unknown")

        # Show the question
        console.print(f"  [bold cyan]Q{step}[/bold cyan]  {question}")
        console.print(f"       [dim]{field_id}[/dim] [dim]({field_type})[/dim]")

        # Get answer
        value = prompt_for_value(field_id, field_info)
        field_values[field_id] = value

        # Re-evaluate
        result = decide(args.url, bundle_id, field_values)
        print_status(result, step, total_fields)
        console.print()

    # Final result
    decision = result["decision"]
    style = _DECISION_STYLE.get(decision, "")
    console.print(f"  [dim]{'─' * 60}[/dim]")
    console.print(f"  Decision: [{style}]{decision}[/{style}] after {step} question{'s' if step != 1 else ''} [dim](of {total_fields} total fields)[/dim]")

    # Show which groups determined the outcome
    trace = result.get("trace") or {}
    group_statuses = trace.get("group_statuses") or {}
    if decision == "not_eligible":
        failed = [g for g, s in group_statuses.items() if s in ("not_satisfied", "not_satisfied")]
        if failed:
            console.print(f"  [red]Failed:[/red] {', '.join(failed)}")
    elif decision == "eligible":
        console.print(f"  [green]All {len(group_statuses)} groups satisfied.[/green]")

    console.print()


if __name__ == "__main__":
    main()
