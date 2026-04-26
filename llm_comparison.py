#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0", "requests>=2.28", "rich>=13.0", "openai>=1.0", "anthropic>=0.40"]
# ///
"""
Compare frontier LLM answers vs deterministic engine on the same test cases.

Tests multiple models across providers. Optionally runs each test multiple
times to measure consistency — LLMs may give different answers on retry,
the engine never does.

Usage:
    uv run llm_comparison.py construction-all-risks/
    uv run llm_comparison.py construction-all-risks/ --runs 3
    uv run llm_comparison.py construction-all-risks/ --models gpt-5.4 claude-sonnet-4-6

Requires OPENAI_API_KEY and/or ANTHROPIC_API_KEY in environment.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import requests
import yaml
from rich.console import Console
from rich.table import Table

console = Console()
DEFAULT_API_URL = "https://api.aethis.ai"

DEFAULT_MODELS = ["gpt-5.4", "gpt-5-mini", "claude-opus-4-6", "claude-sonnet-4-6"]

_ANTHROPIC_PREFIXES = ("claude-",)
_OPENAI_REASONING = ("gpt-5", "o3", "o4")


def _is_anthropic(model: str) -> bool:
    return any(model.startswith(p) for p in _ANTHROPIC_PREFIXES)


def _is_openai_reasoning(model: str) -> bool:
    return any(model.startswith(p) for p in _OPENAI_REASONING)


def load_config(example_dir: Path) -> dict:
    with open(example_dir / "aethis.yaml") as f:
        return yaml.safe_load(f)


def load_tests(example_dir: Path) -> list:
    path = example_dir / "tests" / "scenarios.yaml"
    if not path.exists():
        path = example_dir / "tests.yaml"
    with open(path) as f:
        return yaml.safe_load(f).get("tests", [])


def load_source(example_dir: Path) -> str:
    path = example_dir / "sources" / "source.md"
    if not path.exists():
        path = example_dir / "source.md"
    with open(path) as f:
        return f.read()


def discover_bundle(api_url: str, project_name: str, api_key: Optional[str] = None) -> str:
    headers: dict = {}
    if api_key:
        headers["X-API-Key"] = api_key
    resp = requests.get(f"{api_url}/api/v1/public/bundles", headers=headers, timeout=15)
    resp.raise_for_status()
    normalized = project_name.replace("-", "_").lower()
    for b in resp.json():
        section = b["section_id"].replace("-", "_").lower()
        if normalized in section or section in normalized:
            return b["bundle_id"]
    return ""


def _build_prompt(source_text: str, test: dict) -> str:
    """Build evaluation prompt with full source text — no truncation."""
    facts = []
    for field, value in test["inputs"].items():
        short = field.split(".")[-1].replace("_", " ")
        if isinstance(value, bool):
            facts.append(f"- {short}: {'yes' if value else 'no'}")
        else:
            facts.append(f"- {short}: {value}")
    facts_text = "\n".join(facts)

    return (
        "You are evaluating eligibility based on the following regulation.\n\n"
        f"--- REGULATION ---\n{source_text}\n--- END REGULATION ---\n\n"
        f"Given these facts:\n{facts_text}\n\n"
        "Based ONLY on the regulation above, is the applicant eligible?\n"
        "Answer with exactly one word: eligible, not_eligible, or undetermined.\n"
        "Do not explain. Just the answer."
    )


def _parse_answer(raw: str) -> str:
    raw = raw.strip().lower()
    for label in ("not_eligible", "eligible", "undetermined"):
        if label in raw:
            return label
    return f"parse_error ({raw[:20]})"


def ask_openai(model: str, prompt: str) -> str:
    from openai import OpenAI
    try:
        client = OpenAI()
        kwargs: dict = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        if _is_openai_reasoning(model):
            # Reasoning models use internal CoT tokens that count against
            # max_completion_tokens — need headroom beyond the visible output.
            kwargs["max_completion_tokens"] = 2000
        else:
            kwargs["max_tokens"] = 50
            kwargs["temperature"] = 0
        response = client.chat.completions.create(**kwargs)
        return _parse_answer(response.choices[0].message.content or "")
    except Exception as e:
        return f"error ({str(e)[:40]})"


def ask_anthropic(model: str, prompt: str) -> str:
    import anthropic
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text if response.content else ""
        return _parse_answer(text)
    except Exception as e:
        return f"error ({str(e)[:40]})"


def ask_llm(model: str, source_text: str, test: dict) -> str:
    prompt = _build_prompt(source_text, test)
    if _is_anthropic(model):
        return ask_anthropic(model, prompt)
    return ask_openai(model, prompt)


def ask_engine(api_url: str, bundle_id: str, test: dict, api_key: Optional[str] = None) -> str:
    headers: dict = {}
    if api_key:
        headers["X-API-Key"] = api_key
    resp = requests.post(
        f"{api_url}/api/v1/public/decide",
        json={"bundle_id": bundle_id, "field_values": test["inputs"]},
        headers=headers,
        timeout=30,
    )
    if resp.status_code != 200:
        return f"error ({resp.status_code})"
    return resp.json()["decision"]


def _check_keys(models: list[str]) -> Optional[str]:
    needs_openai = any(not _is_anthropic(m) for m in models)
    needs_anthropic = any(_is_anthropic(m) for m in models)
    missing = []
    if needs_openai and not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if needs_anthropic and not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        return f"Set {' and '.join(missing)} to run this comparison."
    return None


def _style_answer(answer: str, correct: bool) -> str:
    if correct:
        return f"[green]{answer}[/green]"
    return f"[bold red]{answer}[/bold red]"


def _style_consistency(answers: list[str], expected: str) -> str:
    """Format N answers showing consistency. e.g. '3/3 eligible' or '2/3 split'."""
    counts = Counter(answers)
    n = len(answers)
    correct = sum(1 for a in answers if a == expected)

    if len(counts) == 1:
        # All runs agree
        answer = answers[0]
        if answer == expected:
            return f"[green]{correct}/{n} {answer}[/green]"
        return f"[bold red]0/{n} {answer}[/bold red]"

    # Split answers — inconsistency!
    parts = []
    for ans, count in counts.most_common():
        style = "green" if ans == expected else "red"
        parts.append(f"[{style}]{count}×{ans}[/{style}]")
    return f"[yellow]{correct}/{n}[/yellow] {' '.join(parts)}"


def main():
    parser = argparse.ArgumentParser(description="Compare frontier LLMs vs deterministic engine")
    parser.add_argument("example_dir", type=Path)
    parser.add_argument(
        "--models", nargs="+", default=DEFAULT_MODELS,
        help=f"Models to test (default: {' '.join(DEFAULT_MODELS)})",
    )
    parser.add_argument("--runs", type=int, default=1, help="Runs per test per model (default: 1, try 3 for consistency check)")
    parser.add_argument("--url", default=os.environ.get("AETHIS_API_URL", DEFAULT_API_URL))
    parser.add_argument("--bundle-id", help="Skip auto-discovery")
    parser.add_argument("--api-key", default=os.environ.get("AETHIS_API_KEY"), help="API key for engine (or set AETHIS_API_KEY)")
    args = parser.parse_args()

    key_err = _check_keys(args.models)
    if key_err:
        console.print(f"[red]ERROR:[/red] {key_err}")
        sys.exit(1)

    example_dir = args.example_dir.resolve()
    config = load_config(example_dir)
    tests = load_tests(example_dir)
    source_text = load_source(example_dir)
    bundle_id = args.bundle_id or discover_bundle(args.url, config["project"], args.api_key)
    n_runs = args.runs

    # Header
    console.print()
    console.print(f"  [bold]Frontier LLMs vs Aethis Engine[/bold]")
    console.print(f"  [dim]{len(args.models)} models | {len(tests)} tests | {n_runs} run{'s' if n_runs > 1 else ''} per test[/dim]")
    if bundle_id:
        console.print(f"  [dim]Bundle: {bundle_id}[/dim]")
    console.print()

    # Build results table
    table = Table(show_lines=True, title="Results (full source text provided to all models)")
    table.add_column("Test", style="bold", max_width=40)
    table.add_column("Expected", justify="center", width=13)
    for model in args.models:
        short = model.split("/")[-1][:15]
        table.add_column(short, justify="center", width=15)
    table.add_column("Engine", justify="center", width=13)

    # Track scores and consistency
    scores = {m: 0 for m in args.models}
    consistent = {m: 0 for m in args.models}
    engine_correct = 0

    for test in tests:
        name = test["name"]
        expected = test["expect"]["outcome"]

        console.print(f"  [dim]Testing: {name[:50]}...[/dim]", end="\r")

        row = [name[:40], expected]

        for model in args.models:
            answers = [ask_llm(model, source_text, test) for _ in range(n_runs)]

            if n_runs == 1:
                ok = answers[0] == expected
                scores[model] += int(ok)
                consistent[model] += 1  # Single run is trivially consistent
                row.append(_style_answer(answers[0], ok))
            else:
                correct_count = sum(1 for a in answers if a == expected)
                scores[model] += int(correct_count == n_runs)  # Only count as correct if ALL runs agree correctly
                all_same = len(set(answers)) == 1
                consistent[model] += int(all_same)
                row.append(_style_consistency(answers, expected))

        # Engine (always 1 run — deterministic)
        engine_answer = ask_engine(args.url, bundle_id, test, args.api_key) if bundle_id else "no bundle"
        engine_ok = engine_answer == expected
        engine_correct += int(engine_ok)
        row.append(_style_answer(engine_answer, engine_ok))

        table.add_row(*row)

    console.print(table)
    console.print()

    # Summary table
    total = len(tests)
    summary = Table(title="Summary", show_lines=True)
    summary.add_column("Model", style="bold")
    summary.add_column("Correct", justify="center")
    summary.add_column("Accuracy", justify="center")
    if n_runs > 1:
        summary.add_column("Consistent", justify="center", width=12)

    for model in args.models:
        pct = 100 * scores[model] / total
        style = "green" if pct == 100 else "yellow" if pct >= 80 else "red"
        row = [model, f"{scores[model]}/{total}", f"[{style}]{pct:.0f}%[/{style}]"]
        if n_runs > 1:
            cons_pct = 100 * consistent[model] / total
            cons_style = "green" if cons_pct == 100 else "yellow" if cons_pct >= 80 else "red"
            row.append(f"[{cons_style}]{cons_pct:.0f}%[/{cons_style}]")
        summary.add_row(*row)

    engine_row = [
        "[bold]Aethis Engine[/bold]",
        f"[bold]{engine_correct}/{total}[/bold]",
        f"[bold green]{100 * engine_correct / total:.0f}%[/bold green]",
    ]
    if n_runs > 1:
        engine_row.append("[bold green]100%[/bold green]")
    summary.add_row(*engine_row)

    console.print(summary)
    console.print()

    if n_runs > 1:
        inconsistent_models = [m for m in args.models if consistent[m] < total]
        if inconsistent_models:
            console.print(f"  [yellow]Inconsistent models (gave different answers on retry):[/yellow]")
            for m in inconsistent_models:
                console.print(f"    {m}: consistent on {consistent[m]}/{total} tests")
            console.print()
            console.print(f"  [dim]The engine gives the same answer every time — deterministic by design.[/dim]")
            console.print()


if __name__ == "__main__":
    main()
