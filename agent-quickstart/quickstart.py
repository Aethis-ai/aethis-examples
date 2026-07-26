#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "langchain==1.3.14",
#   "langchain-anthropic==1.5.2",
#   "langchain-mcp-adapters==0.3.0",
# ]
# ///
"""Fresh-clone agent quickstart: a LangGraph agent that uses an Aethis decision, with proof.

    uv run agent-quickstart/quickstart.py

The agent reads a plain-English question, calls the Aethis eligibility engine as
an MCP tool, and prints the decision **together with the evidence**: the pinned
rule artefact, replay handles, and the verbatim source passages the rules cite.

If the agent skips the tool, invents a result, or the evaluator returns an
envelope that cannot be audited, this exits non-zero and says exactly what was
missing. Plausible-sounding prose is never accepted as a successful run.

Two modes:

* ``--tool-only``   no model provider involved. Calls the Aethis tool directly
                    over MCP and runs the same proof checks. Free, and the
                    fastest way to confirm your setup before spending tokens.
* (default)         the full agent: your Anthropic key drives a LangGraph agent
                    that decides to call the tool itself.

Prerequisites, costs and data flow: see agent-quickstart/README.md.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aethis_proof import (  # noqa: E402
    AETHIS_DECIDE_TOOL,
    ProofError,
    coerce_text,
    contract_gaps,
    parse_envelope,
    render_proof,
    verify_agent_run,
    verify_decision_envelope,
)

DEFAULT_ENGINE_URL = "https://api.aethis.ai"
DEFAULT_RULESET = "aethis/spacecraft-crew-certification"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MCP_SPEC = "aethis-mcp@0.15.1"

# Every value below is synthetic and non-sensitive: a fictional applicant under a
# fictional statute. Never put real personal data through a public quickstart.
QUESTION = (
    "I am a Vogon applying for spacecraft crew certification. "
    "Am I eligible? Use the Aethis ruleset {ruleset}. "
    "Call aethis_schema first to learn the field names, then call "
    "{tool} with include_explanation set to true, and report the outcome."
)
TOOL_ONLY_FIELD_VALUES = {"space.crew.species": "Vogon"}

# Keep the tool surface small: fewer tools means fewer tokens and a tighter run.
WANTED_TOOLS = ("aethis_schema", AETHIS_DECIDE_TOOL)

EXIT_OK = 0
EXIT_NOT_PROVEN = 2
EXIT_PARTIAL = 3


def _fail(message: str, *hints: str) -> int:
    sys.stdout.flush()
    print(f"\nFAILED: {message}", file=sys.stderr)
    for hint in hints:
        print(f"  {hint}", file=sys.stderr)
    return EXIT_NOT_PROVEN


def check_prerequisites(*, needs_provider_key: bool) -> str | None:
    if shutil.which("npx") is None:
        return (
            "npx was not found on PATH. The Aethis MCP server is an npm package.\n"
            "  Install Node.js 18 or newer: https://nodejs.org"
        )
    if needs_provider_key and not os.environ.get("ANTHROPIC_API_KEY"):
        return (
            "ANTHROPIC_API_KEY is not set. The agent needs your own model-provider key.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  Or run the free check first: uv run agent-quickstart/quickstart.py --tool-only"
        )
    return None


async def load_aethis_tools(mcp_spec: str, engine_url: str) -> list:
    """Register aethis-mcp as a stdio MCP server and pull its tools."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            "aethis": {
                "transport": "stdio",
                "command": "npx",
                "args": ["--yes", mcp_spec],
                # No AETHIS_API_KEY: public rulesets evaluate anonymously.
                "env": {**os.environ, "AETHIS_BASE_URL": engine_url},
            }
        }
    )
    tools = await client.get_tools()
    selected = [t for t in tools if t.name in WANTED_TOOLS]
    missing = sorted(set(WANTED_TOOLS) - {t.name for t in selected})
    if missing:
        raise RuntimeError(
            f"{mcp_spec} did not expose the expected tools: missing {', '.join(missing)}. "
            f"It offered: {', '.join(sorted(t.name for t in tools)) or '(none)'}"
        )
    return selected


async def run_tool_only(args: argparse.Namespace) -> dict:
    """Call the Aethis decision tool directly - no model provider, no cost."""
    tools = await load_aethis_tools(args.mcp_spec, args.engine_url)
    decide = next(t for t in tools if t.name == AETHIS_DECIDE_TOOL)
    print(f"  calling {AETHIS_DECIDE_TOOL} on {args.ruleset} with {TOOL_ONLY_FIELD_VALUES}")
    raw = await decide.ainvoke(
        {
            "ruleset_id": args.ruleset,
            "field_values": TOOL_ONLY_FIELD_VALUES,
            "include_explanation": True,
        }
    )
    return parse_envelope(coerce_text(raw))


async def run_agent(args: argparse.Namespace) -> dict:
    """Run the LangGraph agent and verify it really used the Aethis decision."""
    from langchain.agents import create_agent
    from langchain_anthropic import ChatAnthropic

    tools = await load_aethis_tools(args.mcp_spec, args.engine_url)
    print(f"  tools available to the agent: {', '.join(t.name for t in tools)}")

    agent = create_agent(ChatAnthropic(model=args.model), tools)
    question = QUESTION.format(ruleset=args.ruleset, tool=AETHIS_DECIDE_TOOL)
    print(f"  asking ({args.model}): {question}")

    result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})
    messages = result["messages"]

    final = coerce_text(messages[-1].content)
    print("\nAgent's answer (prose - not evidence)")
    for line in final.splitlines():
        print(f"  {line}")

    return verify_agent_run(
        messages, require_release_contract=not args.allow_partial_proof
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a LangGraph agent that uses an Aethis decision, with proof.",
    )
    parser.add_argument(
        "--tool-only",
        action="store_true",
        help="Skip the model provider: call the Aethis tool directly and verify the result. "
        "No provider key, no token cost.",
    )
    parser.add_argument(
        "--engine-url",
        default=os.environ.get("AETHIS_API_URL", DEFAULT_ENGINE_URL),
        help=f"Aethis evaluator base URL (default: $AETHIS_API_URL or {DEFAULT_ENGINE_URL})",
    )
    parser.add_argument(
        "--ruleset",
        default=os.environ.get("AETHIS_QUICKSTART_RULESET", DEFAULT_RULESET),
        help=f"Public showcase ruleset slug (default: {DEFAULT_RULESET})",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("AETHIS_QUICKSTART_MODEL", DEFAULT_MODEL),
        help=f"Anthropic model id (default: $AETHIS_QUICKSTART_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--mcp-spec",
        default=os.environ.get("AETHIS_MCP_SPEC", DEFAULT_MCP_SPEC),
        help=f"npm spec for the Aethis MCP server (default: {DEFAULT_MCP_SPEC})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("AETHIS_QUICKSTART_TIMEOUT", "300")),
        help="Hard wall-clock limit in seconds (default: 300). Never prompts; always bounded.",
    )
    parser.add_argument(
        "--allow-partial-proof",
        action="store_true",
        help="Waive the immutable-identity and source-reference half of the contract - "
        "useful against an evaluator that predates it. The core invariants (a real tool "
        "call, a valid outcome, replay handles, no verdict beside blocking errors) are "
        "still enforced, the run is labelled PARTIAL PROOF, and it exits non-zero (3) so "
        "no gate can mistake it for success.",
    )
    return parser


async def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    problem = check_prerequisites(needs_provider_key=not args.tool_only)
    if problem:
        return _fail(problem)

    mode = "tool-only (no model provider)" if args.tool_only else f"agent ({args.model})"
    print("Aethis agent quickstart")
    print(f"  mode        {mode}")
    print(f"  evaluator   {args.engine_url}  (anonymous - no Aethis key)")
    print(f"  ruleset     {args.ruleset}")
    print(f"  mcp server  {args.mcp_spec}")
    print("  inputs      synthetic, non-sensitive")
    print()

    started = time.monotonic()
    runner = run_tool_only(args) if args.tool_only else run_agent(args)
    try:
        envelope = await asyncio.wait_for(runner, timeout=args.timeout)
        if args.tool_only:
            envelope = verify_decision_envelope(
                envelope, require_release_contract=not args.allow_partial_proof
            )
    except asyncio.TimeoutError:
        return _fail(
            f"timed out after {args.timeout:.0f}s",
            "Raise the limit with --timeout, or check network access to the evaluator.",
        )
    except ProofError as exc:
        elapsed = time.monotonic() - started
        sys.stdout.flush()
        print(f"\nPROOF CHECK FAILED after {elapsed:.1f}s\n", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print(
            "\nThis is the quickstart working as designed: a result that cannot be audited "
            "is not a result.\n"
            f"The evaluator at {args.engine_url} may predate the immutable-identity and "
            "source-reference contract,\n"
            "or the ruleset may not yet be published with validated citations. Point "
            "--engine-url at an\n"
            "evaluator that serves the current contract, or re-run with "
            "--allow-partial-proof to see\n"
            "how far it gets (that mode never reports success).",
            file=sys.stderr,
        )
        return EXIT_NOT_PROVEN
    except Exception as exc:  # noqa: BLE001 - surface the real cause, never a bare stack
        return _fail(f"{type(exc).__name__}: {exc}")

    elapsed = time.monotonic() - started
    print()
    print(render_proof(envelope))
    print()
    if args.allow_partial_proof:
        gaps = contract_gaps(envelope)
        print(f"PARTIAL PROOF in {elapsed:.1f}s - the release contract was NOT enforced.")
        if gaps:
            print(f"This evaluator did not supply {len(gaps)} required field(s):")
            for gap in gaps:
                print(f"  - {gap}")
        print("This run is not evidence of a fully auditable decision. Exit code 3.")
        return EXIT_PARTIAL
    print(f"PROVEN in {elapsed:.1f}s - the decision above was produced by the Aethis engine,")
    print("pinned to an immutable rule artefact, and traced to its cited source.")
    return EXIT_OK


def main() -> int:
    try:
        return asyncio.run(_main())
    except KeyboardInterrupt:
        return EXIT_NOT_PROVEN


if __name__ == "__main__":
    raise SystemExit(main())
