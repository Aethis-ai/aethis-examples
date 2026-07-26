"""Proof checks for an agent run that used an Aethis decision.

An agent's prose is not evidence. This module inspects the **structured decision
envelope the agent actually received from the tool** and refuses to call a run
successful unless that envelope carries everything an auditor needs:

* the Aethis decision tool was really called (not imagined);
* the outcome is one of the three defined verdicts;
* the rule artefact is pinned - ruleset id, a resolved version (never
  ``unknown``) and a content digest;
* the decision is replayable - a decision id and an inputs hash;
* a positive or negative verdict never sits beside blocking input errors;
* every displayed criterion carries publish-validated source references.

Both ``quickstart.py`` and ``smoke_test.py`` import these functions, so the
tests exercise the same code the quickstart runs - not a reimplementation.

No network, no model provider, no Aethis credential: everything here is pure.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

#: Name of the Aethis evaluation tool exposed over MCP.
AETHIS_DECIDE_TOOL = "aethis_decide"

#: The only outcomes the engine is allowed to report.
DECISIONS = frozenset({"eligible", "not_eligible", "undetermined"})

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_DECISION_ID = re.compile(r"^dec_[A-Za-z0-9_-]{16}$")
_ENGINE_VERSION = re.compile(r"^aethis-core@\d+\.\d+\.\d+")
_UNRESOLVED = frozenset({"", "unknown", "none", "null"})

# The MCP server wraps tool output in a fenced block behind a short preface so a
# consumer can see where untrusted data starts. Older releases returned bare
# JSON. Accept both.
_FENCE = re.compile(r"```(?:json)?\s*\n(?P<body>.*?)\n?```", re.DOTALL)


class ProofError(Exception):
    """The run did not produce a verifiable Aethis decision.

    ``code`` is a short stable identifier for the failure class and ``problems``
    lists every individual check that failed, so a caller can print the whole
    picture instead of only the first thing that went wrong.
    """

    def __init__(self, code: str, summary: str, problems: Iterable[str] = ()) -> None:
        self.code = code
        self.summary = summary
        self.problems = list(problems)
        detail = "".join(f"\n  - {p}" for p in self.problems)
        super().__init__(f"[{code}] {summary}{detail}")


# --------------------------------------------------------------------------
# Reading the envelope back out of the conversation
# --------------------------------------------------------------------------


def parse_envelope(text: str) -> dict[str, Any]:
    """Parse a decision envelope out of raw tool output.

    Handles both the fenced form the MCP server emits today and the bare-JSON
    form older releases returned.
    """
    if not isinstance(text, str) or not text.strip():
        raise ProofError("unreadable-tool-output", "The Aethis tool returned no text.")

    candidates: list[str] = [m.group("body") for m in _FENCE.finditer(text)]
    candidates.append(text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ProofError(
        "unreadable-tool-output",
        "The Aethis tool output was not a JSON decision envelope.",
        [f"first 200 characters: {text[:200]!r}"],
    )


def coerce_text(content: Any) -> str:
    """Flatten LangChain message content into plain text.

    Content arrives either as a string or as a list of content parts
    (``[{"type": "text", "text": "..."}]`` - what the MCP adapter returns).
    Stringifying the list directly yields a Python repr, not JSON, so the
    envelope parser must never see it.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(coerce_text(part) for part in content)
    if isinstance(content, dict):
        return str(content.get("text", ""))
    return str(content)


def _message_type(message: Any) -> str:
    return str(getattr(message, "type", "") or "")


def requested_tool_calls(messages: Iterable[Any]) -> list[str]:
    """Names of every tool the model asked for, in order."""
    names: list[str] = []
    for message in messages:
        if _message_type(message) != "ai":
            continue
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                names.append(str(name))
    return names


def tool_outputs(messages: Iterable[Any], tool_name: str) -> list[str]:
    """Raw text results returned by ``tool_name``, in order."""
    outputs: list[str] = []
    for message in messages:
        if _message_type(message) != "tool":
            continue
        if str(getattr(message, "name", "") or "") != tool_name:
            continue
        outputs.append(coerce_text(getattr(message, "content", "")))
    return outputs


# --------------------------------------------------------------------------
# The contract checks
# --------------------------------------------------------------------------


def _check_source_reference(ref: Any, where: str, problems: list[str]) -> None:
    if not isinstance(ref, dict):
        problems.append(f"{where}: source reference is not an object")
        return
    for field in ("title", "authority", "licence", "verified_at", "deep_link"):
        if not str(ref.get(field) or "").strip():
            problems.append(f"{where}: source reference is missing '{field}'")
    url = str(ref.get("url") or "")
    if not url.startswith("https://"):
        problems.append(f"{where}: source reference url is not HTTPS ({url!r})")
    digest = str(ref.get("content_digest") or "")
    if not _SHA256.match(digest):
        problems.append(
            f"{where}: source reference content_digest is not sha256:<64 hex> ({digest!r})"
        )
    quote = ref.get("quote")
    if not isinstance(quote, dict) or not str(quote.get("exact") or "").strip():
        problems.append(f"{where}: source reference carries no verbatim quote")


def source_references(envelope: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every ``(criterion_id, reference)`` pair carried by the explanation."""
    found: list[tuple[str, dict[str, Any]]] = []
    explanation = envelope.get("explanation")
    if not isinstance(explanation, dict):
        return found
    for group in explanation.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for criterion in group.get("criteria") or []:
            if not isinstance(criterion, dict):
                continue
            criterion_id = str(criterion.get("criterion_id") or "?")
            for ref in criterion.get("source_references") or []:
                found.append((criterion_id, ref))
    return found


def contract_gaps(envelope: dict[str, Any]) -> list[str]:
    """Release-contract fields this envelope does not carry.

    These are the parts of the contract an older evaluator - or a ruleset
    published without validated citations - cannot yet supply: a resolved
    version, a content digest, and per-criterion source references. Everything
    else in :func:`verify_decision_envelope` is always required.
    """
    problems: list[str] = []

    version = str(envelope.get("ruleset_version") or "").strip()
    if version.lower() in _UNRESOLVED:
        problems.append(
            f"ruleset_version is {envelope.get('ruleset_version')!r} - a published ruleset "
            "always reports a resolved version, so this decision cannot be replayed"
        )

    digest = str(envelope.get("content_digest") or "")
    if not _SHA256.match(digest):
        problems.append(
            f"content_digest is not sha256:<64 hex> ({envelope.get('content_digest')!r})"
        )

    refs = source_references(envelope)
    if not refs:
        problems.append(
            "no criterion carries source_references - the decision is not traceable to "
            "its authority (request include_explanation, and publish the ruleset with "
            "publish-validated citations)"
        )
    for criterion_id, ref in refs:
        _check_source_reference(ref, f"criterion {criterion_id}", problems)

    return problems


def verify_decision_envelope(
    envelope: dict[str, Any],
    *,
    require_release_contract: bool = True,
) -> dict[str, Any]:
    """Assert an envelope satisfies the proof contract; return it unchanged.

    Always enforced (these can never be waived):

    * the outcome is one of the three defined verdicts;
    * the rule artefact is identified;
    * the decision is addressable and replayable - decision id, inputs hash,
      engine version;
    * a verdict never sits beside blocking input errors.

    Additionally enforced when ``require_release_contract`` is true (the
    default): the immutable-identity and source-reference fields listed by
    :func:`contract_gaps`.

    Raises :class:`ProofError` listing every failed check.
    """
    problems: list[str] = []

    decision = envelope.get("decision")
    if decision not in DECISIONS:
        problems.append(f"decision is {decision!r}, expected one of {sorted(DECISIONS)}")

    if not str(envelope.get("ruleset_id") or "").strip():
        problems.append("ruleset_id is missing - the decided rule artefact is unidentified")

    inputs_hash = str(envelope.get("inputs_hash") or "")
    if not _SHA256.match(inputs_hash):
        problems.append(
            f"inputs_hash is not sha256:<64 hex> ({envelope.get('inputs_hash')!r})"
        )

    decision_id = str(envelope.get("decision_id") or "")
    if not _DECISION_ID.match(decision_id):
        problems.append(
            f"decision_id is not dec_<16 chars> ({envelope.get('decision_id')!r})"
        )

    engine = str(envelope.get("engine_version") or "")
    if not _ENGINE_VERSION.match(engine):
        problems.append(
            f"engine_version is not aethis-core@<semver> ({envelope.get('engine_version')!r})"
        )

    field_errors = envelope.get("field_errors") or {}
    if field_errors and decision != "undetermined":
        problems.append(
            f"decision is {decision!r} but {len(field_errors)} blocking field error(s) are "
            "present - a verdict must never be computed from rejected input"
        )

    if require_release_contract:
        problems.extend(contract_gaps(envelope))

    if problems:
        raise ProofError(
            "envelope-does-not-meet-contract",
            "The decision envelope does not carry verifiable proof.",
            problems,
        )
    return envelope


def verify_agent_run(
    messages: Iterable[Any],
    *,
    require_release_contract: bool = True,
) -> dict[str, Any]:
    """Verify an agent transcript really used an Aethis decision.

    Returns the verified envelope. Raises :class:`ProofError` when the agent
    never called the tool, when the tool output is unreadable, or when the
    envelope fails the contract above.
    """
    messages = list(messages)

    if AETHIS_DECIDE_TOOL not in requested_tool_calls(messages):
        raise ProofError(
            "no-aethis-tool-call",
            f"The agent never called {AETHIS_DECIDE_TOOL}.",
            [
                "tools the agent did call: "
                + (", ".join(requested_tool_calls(messages)) or "(none)"),
                "an answer produced without the tool is the model's opinion, not a decision",
            ],
        )

    outputs = tool_outputs(messages, AETHIS_DECIDE_TOOL)
    if not outputs:
        raise ProofError(
            "no-aethis-tool-result",
            f"The agent requested {AETHIS_DECIDE_TOOL} but no result came back.",
        )

    envelope = parse_envelope(outputs[-1])
    return verify_decision_envelope(
        envelope, require_release_contract=require_release_contract
    )


# --------------------------------------------------------------------------
# Display
# --------------------------------------------------------------------------


def render_proof(envelope: dict[str, Any]) -> str:
    """Human-readable proof block: identity, replay handles, and citations."""
    lines: list[str] = []
    add = lines.append

    add("Decision")
    add(f"  outcome         {envelope.get('decision')}")
    add(f"  ruleset         {envelope.get('slug') or envelope.get('ruleset_id')}")
    add(f"  ruleset_id      {envelope.get('ruleset_id')}")
    add(f"  ruleset_version {envelope.get('ruleset_version')}")
    add(f"  content_digest  {envelope.get('content_digest')}")
    add("")
    add("Replay handles")
    add(f"  decision_id     {envelope.get('decision_id')}")
    add(f"  inputs_hash     {envelope.get('inputs_hash')}")
    add(f"  engine_version  {envelope.get('engine_version')}")
    add(f"  decision_time   {envelope.get('decision_time')}")

    refs = source_references(envelope)
    add("")
    add(f"Source references ({len(refs)})")
    if not refs:
        add("  (none)")
    for criterion_id, ref in refs:
        quote = (ref.get("quote") or {}).get("exact", "")
        add(f"  {criterion_id}")
        add(f"    {ref.get('title')} - {ref.get('authority')}")
        locator = ref.get("locator")
        if locator:
            add(f"    locator       {locator}")
        add(f"    licence       {ref.get('licence')}")
        add(f"    verified_at   {ref.get('verified_at')}")
        add(f"    digest        {ref.get('content_digest')}")
        add(f'    quote         "{quote}"')
        add(f"    open          {ref.get('deep_link')}")

    field_errors = envelope.get("field_errors") or {}
    if field_errors:
        add("")
        add(f"Blocking input errors ({len(field_errors)})")
        for field, message in field_errors.items():
            add(f"  {field}: {message}")

    return "\n".join(lines)
