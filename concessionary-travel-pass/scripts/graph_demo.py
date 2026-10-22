#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0", "requests>=2.28", "rich>=13.0"]
# ///
"""
Fetch and read the ruleset-map GET /graph for this example.

Demonstrates the public `/graph` endpoint (see
https://docs.aethis.ai/reference/graph): every field, every compiled
criterion, the groups they roll up into, and how those groups combine
into the outcome — the same compiled logic /schema and /explain describe,
laid out as nodes and edges. Public rulesets are reachable anonymously,
the same as /decide and /schema.

This example's graph is a good one to read closely because criterion
`age_route` exercises the `years_between` completed-whole-years date
operator. This script prints its raw compiled expression (`display.expr`) so
you can see the operator by name, not just its plain-English sentence.

Usage:
    uv run scripts/graph_demo.py
    uv run scripts/graph_demo.py --url http://localhost:8080 --ruleset-id ...
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
DEFAULT_API_URL = "https://api.aethis.ai"

_NODE_STYLE = {
    "field": "cyan",
    "criterion": "yellow",
    "group": "magenta",
    "outcome": "bold green",
}


def load_config(example_dir: Path) -> dict:
    path = example_dir / "aethis.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def discover_ruleset(api_url: str, project_name: str) -> str:
    resp = requests.get(f"{api_url}/api/v1/public/rulesets", timeout=15)
    resp.raise_for_status()
    for r in resp.json():
        slug = r.get("slug") or ""
        if slug == f"aethis/{project_name}" or slug.endswith(f"/{project_name}"):
            return r["ruleset_id"]
    console.print(
        f"[red]ERROR:[/red] No public ruleset found matching [bold]{project_name}[/bold]"
    )
    sys.exit(1)


def fetch_graph(api_url: str, ruleset_id: str) -> dict:
    """GET /api/v1/public/rulesets/{ruleset_id}/graph — no API key required
    for a public ruleset, the same anonymous-access rule as /decide and
    /schema."""
    resp = requests.get(
        f"{api_url}/api/v1/public/rulesets/{ruleset_id}/graph", timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "example_dir",
        type=Path,
        nargs="?",
        default=Path(__file__).resolve().parent.parent,
        help="Path to this example directory (default: the parent of scripts/)",
    )
    parser.add_argument(
        "--url", default=os.environ.get("AETHIS_API_URL", DEFAULT_API_URL)
    )
    parser.add_argument("--ruleset-id", help="Skip auto-discovery")
    parser.add_argument(
        "--json", action="store_true", help="Dump the raw graph JSON instead of a table"
    )
    args = parser.parse_args()

    example_dir = args.example_dir.resolve()
    config = load_config(example_dir)
    project_name = config["project"]
    ruleset_id = args.ruleset_id or discover_ruleset(args.url, project_name)

    envelope = fetch_graph(args.url, ruleset_id)

    if args.json:
        print(json.dumps(envelope, indent=2))
        return

    graph = envelope["graph"]
    stats = graph["stats"]

    console.print()
    console.print(
        Panel(
            f"[bold]{envelope['name']}[/bold]\n[dim]{envelope['slug']}  ·  {envelope['ruleset_id']}[/dim]",
            title="GET /graph",
            subtitle=f"[dim]{args.url}[/dim]",
            border_style="cyan",
        )
    )
    console.print(
        f"  [dim]{stats['total_fields']} fields, {stats['total_criteria']} criteria, "
        f"{stats['total_groups']} groups, {stats['sections']} section(s)[/dim]"
    )
    console.print()

    table = Table(title="Nodes")
    table.add_column("Type")
    table.add_column("ID", style="dim")
    table.add_column("Sentence / label")
    for node in graph["nodes"]:
        style = _NODE_STYLE.get(node["type"], "")
        display = node.get("display") or {}
        text = display.get("sentence") or node.get("label") or "—"
        table.add_row(f"[{style}]{node['type']}[/{style}]", node["id"], text)
    console.print(table)
    console.print()

    # The years_between criterion in detail — sentence, structured route
    # tree, and raw compiled expression side by side (the "three altitudes"
    # documented in the /graph reference page).
    for node in graph["nodes"]:
        if node["type"] != "criterion":
            continue
        display = node.get("display") or {}
        expr = display.get("expr") or {}
        if "years_between" not in json.dumps(expr):
            continue
        console.print(
            Panel(
                f"[bold]{node['id']}[/bold]  [dim](group: {node.get('group')})[/dim]\n\n"
                f"[dim]sentence:[/dim]  {display.get('sentence')}\n\n"
                f"[dim]expr (raw compiled AST):[/dim]\n{json.dumps(expr, indent=2)}",
                title="years_between criterion",
                border_style="yellow",
            )
        )

    console.print(
        "  [dim]Mermaid diagram is also in the response — pipe --json | jq -r .graph.mermaid into any renderer.[/dim]"
    )
    console.print()


if __name__ == "__main__":
    main()
