#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "langchain==1.3.14",
#   "langchain-anthropic==1.5.2",
#   "langchain-mcp-adapters==0.3.0",
#   "mcp>=1.24.0,<2",
#   "rfc8785==0.1.4",
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
import json
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from aethis_proof import (
    AETHIS_DECIDE_TOOL,
    ProofError,
    coerce_text,
    envelope_names_ruleset,
    render_proof,
    verify_agent_run,
    verify_decision_envelope,
    verify_tool_only_run,
)

DEFAULT_ENGINE_URL = "https://api.aethis.ai"
DEFAULT_RULESET = "aethis/spacecraft-crew-certification"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MCP_SPEC = "aethis-mcp@0.17.4"
MAX_MODEL_OUTPUT_TOKENS = 1024
MAX_MODEL_RETRIES = 1
MAX_AGENT_STEPS = 6

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

# The MCP server is a child process, so it inherits whatever we hand it. Build
# that environment explicitly rather than forwarding os.environ wholesale: an
# AETHIS_API_KEY sitting in the shell would silently authenticate the run
# against the developer's own tenant and quota while this script reported an
# anonymous call. Only what the child genuinely needs is passed through.
PASSTHROUGH_ENV = (
    "PATH",
    "HOME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SystemRoot",
    "APPDATA",
    "USERPROFILE",
    "COMSPEC",
    "PATHEXT",
    "NODE_OPTIONS",
    "NODE_EXTRA_CA_CERTS",
    "NPM_CONFIG_CACHE",
    "NPM_CONFIG_PREFIX",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)

# Never forwarded: anything that could authenticate the evaluator call.
WITHHELD_ENV = ("AETHIS_API_KEY", "AETHIS_API_TOKEN")


def child_environment(engine_url: str) -> dict[str, str]:
    """The environment handed to the MCP server: no Aethis credential."""
    env = {k: v for k, v in os.environ.items() if k in PASSTHROUGH_ENV}
    env["AETHIS_BASE_URL"] = engine_url
    return env


EXIT_OK = 0
EXIT_NOT_PROVEN = 2


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
                "env": child_environment(engine_url),
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


async def run_tool_only(args: argparse.Namespace, *, load_tools=load_aethis_tools) -> dict:
    """Call the Aethis decision tool directly - no model provider, no cost.

    ``load_tools`` is injectable for the same reason it is on :func:`run_agent`:
    so the smoke tests can drive this exact function, ruleset guard included,
    without a network call.
    """
    tools = await load_tools(args.mcp_spec, args.engine_url)
    decide = next(t for t in tools if t.name == AETHIS_DECIDE_TOOL)
    print(f"  calling {AETHIS_DECIDE_TOOL} on {args.ruleset} with {TOOL_ONLY_FIELD_VALUES}")
    call = {
        "name": AETHIS_DECIDE_TOOL,
        "id": "tool-only-decision",
        "type": "tool_call",
        "args": {
            "ruleset_id": args.ruleset,
            "field_values": TOOL_ONLY_FIELD_VALUES,
            "include_explanation": True,
        },
    }
    raw = await decide.ainvoke(call)
    envelope = verify_tool_only_run(call, raw, expected_ruleset=args.ruleset)
    args._run_evidence = {
        "tool_output": coerce_text(raw.content),
        "tool_message": _serialize_message(raw),
        "tool_call": call,
    }
    if not envelope_names_ruleset(envelope, args.ruleset):
        raise ProofError(
            "wrong-ruleset-decided",
            f"Asked for {args.ruleset!r} but the evaluator decided "
            f"{envelope.get('slug') or envelope.get('ruleset_id')!r}.",
        )
    return envelope


def default_model(args: argparse.Namespace):
    """The chat model the agent runs on. Swapped for a scripted one in tests."""
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=args.model,
        max_tokens=MAX_MODEL_OUTPUT_TOKENS,
        max_retries=MAX_MODEL_RETRIES,
    )


async def run_agent(
    args: argparse.Namespace,
    *,
    load_tools=load_aethis_tools,
    make_model=default_model,
) -> dict:
    """Run the agent and verify it really used the Aethis decision.

    ``load_tools`` and ``make_model`` are injectable so the smoke tests can
    drive this exact function - verification wiring included - without a model
    provider or a network call.
    """
    from langchain.agents import create_agent

    tools = await load_tools(args.mcp_spec, args.engine_url)
    print(f"  tools available to the agent: {', '.join(t.name for t in tools)}")

    agent = create_agent(make_model(args), tools)
    question = QUESTION.format(ruleset=args.ruleset, tool=AETHIS_DECIDE_TOOL)
    print(f"  asking ({args.model}): {question}")

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"recursion_limit": MAX_AGENT_STEPS},
    )
    messages = result["messages"]
    args._run_evidence = {"messages": [_serialize_message(message) for message in messages]}

    _assert_safe_evidence(args._run_evidence)
    final = coerce_text(messages[-1].content)
    print("\nAgent's answer (prose - not evidence)")
    for line in final.splitlines():
        print(f"  {line}")

    return verify_agent_run(
        messages,
        require_release_contract=True,
        expected_ruleset=args.ruleset,
    )


def _serialize_message(message: Any) -> dict[str, Any]:
    """Keep only replay-relevant conversation fields; credentials never enter messages."""
    item: dict[str, Any] = {"type": str(getattr(message, "type", ""))}
    raw_content = getattr(message, "content", "")
    item["raw_content"] = raw_content
    content = coerce_text(raw_content)
    if content:
        item["content"] = content
    name = str(getattr(message, "name", "") or "")
    if name:
        item["name"] = name
    for key in (
        "tool_call_id",
        "status",
        "artifact",
        "response_metadata",
        "usage_metadata",
        "invalid_tool_calls",
    ):
        value = getattr(message, key, None)
        if value is not None:
            item[key] = value
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        item["tool_calls"] = tool_calls
    return item


_SENSITIVE = re.compile(
    r"(?:ak_[A-Za-z0-9_-]+|sk-ant-[A-Za-z0-9_-]+|ANTHROPIC_API_KEY|credential|//[^/\s]*@)", re.I
)


def _assert_safe_evidence(value: Any) -> None:
    sentinels = [
        os.environ.get(key, "")
        for key in ("ANTHROPIC_API_KEY", "AETHIS_API_KEY", "AETHIS_DECIDE_KEY", "AETHIS_API_TOKEN")
    ]
    if isinstance(value, str) and (
        _SENSITIVE.search(value) or any(len(secret) > 8 and secret in value for secret in sentinels)
    ):
        raise ProofError(
            "unsafe-evidence", "evidence contains a credential sentinel or secret-like value"
        )
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {
                "credential",
                "api_key",
                "x-api-key",
                "authorization",
                "password",
                "token",
                "secret",
            }:
                raise ProofError("unsafe-evidence", f"evidence contains sensitive key {key!r}")
            _assert_safe_evidence(str(key))
            _assert_safe_evidence(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_safe_evidence(child)


def write_evidence(
    args: argparse.Namespace, envelope: dict[str, Any], duration_seconds: float
) -> None:
    """Write a strict, credential-free artifact for independent replay checks."""
    if not args.evidence_file:
        return
    _assert_safe_evidence(envelope)
    _assert_safe_evidence(getattr(args, "_run_evidence", {}))
    artifact = {
        "schema_version": 1,
        "strict_contract_verified": True,
        "mode": "tool-only" if args.tool_only else "agent",
        "args": {
            "engine_url": args.engine_url,
            "ruleset": args.ruleset,
            "mcp_spec": args.mcp_spec,
            "model": None if args.tool_only else args.model,
            "timeout_seconds": args.timeout,
        },
        "duration_seconds": duration_seconds,
        "envelope": envelope,
        "run_evidence": getattr(args, "_run_evidence", {}),
    }
    _assert_safe_evidence(artifact)
    args.evidence_file.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")


def validate_arguments(args: argparse.Namespace) -> None:
    parsed = urlsplit(args.engine_url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ProofError(
            "unsafe-arguments",
            "engine URL must be a plain HTTP(S) endpoint without credentials, query or fragment",
        )
    if not re.fullmatch(r"aethis-mcp@\d+\.\d+\.\d+", args.mcp_spec):
        raise ProofError(
            "unsafe-arguments", "MCP spec must be an exact public aethis-mcp registry version"
        )
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ProofError("unsafe-arguments", "timeout must be positive and finite")
    _assert_safe_evidence(
        {
            "engine_url": args.engine_url,
            "ruleset": args.ruleset,
            "mcp_spec": args.mcp_spec,
            "model": args.model,
        }
    )


def _default_timeout() -> float:
    """Read AETHIS_QUICKSTART_TIMEOUT, failing with a message rather than a traceback."""
    raw = os.environ.get("AETHIS_QUICKSTART_TIMEOUT")
    if raw is None:
        return 300.0
    try:
        value = float(raw)
    except ValueError:
        raise SystemExit("AETHIS_QUICKSTART_TIMEOUT must be a number of seconds.") from None
    if value <= 0:
        raise SystemExit("AETHIS_QUICKSTART_TIMEOUT must be greater than zero.")
    return value


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        super().error("Invalid arguments; check option names and value types.")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
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
        default=_default_timeout(),
        help="Hard wall-clock limit in seconds (default: 300). Never prompts; always bounded.",
    )
    parser.add_argument(
        "--evidence-file",
        type=Path,
        help="Write a strict, credential-free JSON evidence artifact after a proven run.",
    )
    return parser


async def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        validate_arguments(args)
    except (ProofError, ValueError):
        return _fail("invalid or unsafe quickstart arguments")

    problem = check_prerequisites(needs_provider_key=not args.tool_only)
    if problem:
        return _fail(problem)

    mode = "tool-only (no model provider)" if args.tool_only else f"agent ({args.model})"
    print("Aethis agent quickstart")
    print(f"  mode        {mode}")
    print(f"  evaluator   {args.engine_url}  (this script sends no Aethis credential)")
    print(f"  ruleset     {args.ruleset}")
    print(f"  mcp server  {args.mcp_spec}")
    if not args.tool_only:
        print(
            "  provider    at most 3 model turns, 1024 output tokens each, and one retry per turn"
        )
    print("  inputs      synthetic, non-sensitive")
    for name in WITHHELD_ENV:
        if os.environ.get(name):
            print(f"  note        {name} is set in your shell and is NOT forwarded")
    print()

    started = time.monotonic()
    runner = run_tool_only(args) if args.tool_only else run_agent(args)
    try:
        envelope = await asyncio.wait_for(runner, timeout=args.timeout)
        if args.tool_only:
            envelope = verify_decision_envelope(envelope, require_release_contract=True)
        _assert_safe_evidence(envelope)
        _assert_safe_evidence(getattr(args, "_run_evidence", {}))
        write_evidence(args, envelope, time.monotonic() - started)
    except TimeoutError:
        return _fail(
            f"timed out after {args.timeout:.0f}s",
            "Raise the limit with --timeout, or check network access to the evaluator.",
        )
    except ProofError as exc:
        elapsed = time.monotonic() - started
        sys.stdout.flush()
        print(f"\nPROOF CHECK FAILED after {elapsed:.1f}s\n", file=sys.stderr)
        print(_safe_diagnostic(str(exc)), file=sys.stderr)
        print(
            "\nThis is the quickstart working as designed: a result that cannot be audited "
            "is not a result.\n"
            f"The evaluator at {args.engine_url} may predate the immutable-identity and "
            "source-reference contract,\n"
            "or the ruleset may not yet be published with validated citations. Point "
            "--engine-url at an\n"
            "evaluator that serves the current contract. This quickstart deliberately "
            "does not offer a partial-proof mode.",
            file=sys.stderr,
        )
        return EXIT_NOT_PROVEN
    except Exception as exc:  # surface the real cause, never a bare traceback
        return _fail(f"{type(exc).__name__}: {_safe_diagnostic(str(exc))}")

    elapsed = time.monotonic() - started
    print()
    print(render_proof(envelope))
    print()
    print(f"PROVEN in {elapsed:.1f}s - the decision above came from the evaluator at")
    print(f"{args.engine_url}, is pinned to an immutable rule artefact, and every")
    print("reported criterion carries a citation with a checkable digest. Fetching a")
    print("cited document to recompute its digest is a separate step this script")
    print("does not perform.")
    return EXIT_OK


def main() -> int:
    try:
        return asyncio.run(_main())
    except KeyboardInterrupt:
        return EXIT_NOT_PROVEN


def _safe_diagnostic(message: str) -> str:
    withheld = [
        os.environ.get(key, "") for key in (*WITHHELD_ENV, "ANTHROPIC_API_KEY", "AETHIS_DECIDE_KEY")
    ]
    if (
        _SENSITIVE.search(message)
        or any(value and value in message for value in withheld)
        or re.search(r"https?://[^\s/@]+:[^\s/@]+@|password|x-api-key", message, re.I)
    ):
        return "diagnostic withheld because it may contain sensitive data"
    return message


if __name__ == "__main__":
    raise SystemExit(main())
