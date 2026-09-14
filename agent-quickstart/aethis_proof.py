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
* **every** criterion the explanation reports carries a publish-validated
  source reference - per criterion, not in aggregate.

Both ``quickstart.py`` and ``smoke_test.py`` import these functions, so the
tests exercise the same code the quickstart runs - not a reimplementation.

No network, no model provider, no Aethis credential: everything here is pure.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from input_identity import decision_input_hash

#: Name of the Aethis evaluation tool exposed over MCP.
AETHIS_DECIDE_TOOL = "aethis_decide"

#: The only outcomes the engine is allowed to report.
DECISIONS = frozenset({"eligible", "not_eligible", "undetermined"})

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_DECISION_ID = re.compile(r"^dec_[A-Za-z0-9_-]{16}$")
_ENGINE_VERSION = re.compile(r"^aethis-core@\d+\.\d+\.\d+")
_UNRESOLVED = frozenset({"", "unknown", "none", "null"})

# Two tool-output wire shapes are in the wild, and both are exercised by
# recorded payloads in fixtures/wire/ captured from the servers themselves:
#
#   aethis-mcp <= 0.15.1  bare pretty-printed JSON
#   aethis-mcp >= 0.16.0  a short preface, then the JSON inside an
#                         <api_response label="json"> ... </api_response> fence
#
# The fence exists so a consumer can see where untrusted data begins; the
# server neutralises any literal closing tag in the payload, so matching to the
# first closing tag is safe.
_API_RESPONSE = re.compile(
    r"<api_response\b[^>]*>\r?\n(?P<body>.*?)\r?\n</api_response>", re.DOTALL
)
# Tolerated defensively; no released server emits this shape.
_MARKDOWN_FENCE = re.compile(r"```(?:json)?\s*\n(?P<body>.*?)\n?```", re.DOTALL)


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


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while refusing duplicate keys at every depth."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


# --------------------------------------------------------------------------
# Reading the envelope back out of the conversation
# --------------------------------------------------------------------------


def parse_envelope(text: str) -> dict[str, Any]:
    """Parse a decision envelope out of raw tool output.

    Handles the fenced form aethis-mcp emits from 0.16.0 and the bare-JSON form
    0.15.1 and earlier returned.
    """
    if not isinstance(text, str) or not text.strip():
        raise ProofError("unreadable-tool-output", "The Aethis tool returned no text.")

    # Exactly one fenced block, or none. "First parseable block wins" is the
    # wrong default for a fence whose job is to mark a trust boundary: a payload
    # carrying a second, forged block could decide which one a consumer reads.
    # aethis_decide returns a single block, so more than one means something
    # unexpected happened and the honest response is to refuse.
    if re.search(r'<api_response\b[^>]*\blabel=["\']api_error["\']', text, re.I):
        raise ProofError("failed-tool-result", "The Aethis tool reported an API error.")
    fenced = _API_RESPONSE.findall(text) or _MARKDOWN_FENCE.findall(text)
    if len(fenced) > 1:
        raise ProofError(
            "ambiguous-tool-output",
            f"The Aethis tool output contained {len(fenced)} fenced blocks; expected one.",
            ["refusing to guess which block is the real decision"],
        )
    candidates: list[str] = list(fenced)
    candidates.append(text)

    duplicate_key_error: ValueError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate, object_pairs_hook=_unique_json_object)
        except ValueError as exc:
            if str(exc).startswith("duplicate JSON object key"):
                duplicate_key_error = exc
            continue
        except TypeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    if duplicate_key_error is not None:
        raise ProofError(
            "duplicate-json-key",
            "The Aethis tool output contains a duplicate JSON object key.",
            [str(duplicate_key_error)],
        )

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


def reported_criteria(envelope: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every ``(criterion_id, criterion)`` the explanation reports.

    This is the denominator for the citation check: every criterion shown to a
    reader, whatever its status. A pending criterion is still a published rule
    with an authority behind it, so it is not exempt.
    """
    found: list[tuple[str, dict[str, Any]]] = []
    explanation = envelope.get("explanation")
    if not isinstance(explanation, dict):
        return found
    groups = explanation.get("groups") or []
    if not isinstance(groups, list):
        raise ProofError("invalid-explanation", "The explanation groups are not a list.")
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ProofError(
                "invalid-explanation",
                f"Explanation group {group_index} is not an object.",
            )
        criteria = group.get("criteria") or []
        if not isinstance(criteria, list):
            raise ProofError(
                "invalid-explanation",
                f"Explanation group {group_index} criteria are not a list.",
            )
        for criterion_index, criterion in enumerate(criteria):
            if not isinstance(criterion, dict):
                raise ProofError(
                    "invalid-explanation",
                    f"Criterion {criterion_index} in explanation group {group_index} "
                    "is not an object.",
                )
            found.append((str(criterion.get("criterion_id") or "?"), criterion))
    return found


def source_references(envelope: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every ``(criterion_id, reference)`` pair carried by the explanation."""
    return [
        (criterion_id, ref)
        for criterion_id, criterion in reported_criteria(envelope)
        for ref in criterion.get("source_references") or []
    ]


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

    # Per criterion, not in aggregate. The denominator is every criterion the
    # explanation reports: one uncited criterion is one rule whose authority the
    # reader cannot check, and an aggregate count would let a mostly-cited
    # ruleset pass while hiding exactly that.
    criteria = reported_criteria(envelope)
    if not criteria:
        problems.append(
            "the response carries no explanation, so no citation can be checked "
            "(request include_explanation)"
        )
    uncited = [cid for cid, criterion in criteria if not (criterion.get("source_references") or [])]
    if uncited:
        problems.append(
            f"{len(uncited)} of {len(criteria)} reported criteria carry no "
            f"source_references, so their authority cannot be checked: "
            f"{', '.join(uncited)}"
        )
    for criterion_id, ref in source_references(envelope):
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
        problems.append(f"inputs_hash is not sha256:<64 hex> ({envelope.get('inputs_hash')!r})")

    decision_id = str(envelope.get("decision_id") or "")
    if not _DECISION_ID.match(decision_id):
        problems.append(f"decision_id is not dec_<16 chars> ({envelope.get('decision_id')!r})")

    engine = str(envelope.get("engine_version") or "")
    if not _ENGINE_VERSION.match(engine):
        problems.append(
            f"engine_version is not aethis-core@<semver> ({envelope.get('engine_version')!r})"
        )

    field_errors = envelope.get("field_errors") or {}
    if field_errors:
        problems.append("blocking field_errors are not a terminal successful decision")
    if decision not in {"eligible", "not_eligible"}:
        problems.append("decision is not terminal")
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


def envelope_names_ruleset(envelope: dict[str, Any], ruleset: str) -> bool:
    """True when this envelope decided the ruleset the caller asked for."""
    wanted = ruleset.strip()
    if "/" not in wanted:
        return wanted == envelope.get("ruleset_id")
    return wanted in {
        str(envelope.get("slug") or "").strip(),
        str(envelope.get("ruleset_id") or "").strip(),
    }


def verify_tool_payload(message: Any) -> dict[str, Any]:
    """Read a successful MCP message without discarding structured content."""
    if getattr(message, "status", None) != "success":
        raise ProofError("failed-tool-result", "Tool success status is missing or false.")
    envelope = parse_envelope(coerce_text(getattr(message, "content", "")))
    artifact = getattr(message, "artifact", None)
    if artifact is not None:
        if not isinstance(artifact, dict):
            raise ProofError("contradictory-tool-artifact", "Unexpected tool artifact shape.")
        structured = artifact.get("structured_content", artifact.get("structuredContent", artifact))
        if structured != envelope:
            raise ProofError(
                "contradictory-tool-artifact", "Tool text and structured artifact disagree."
            )
    return envelope


def verify_agent_run(
    messages: Iterable[Any],
    *,
    require_release_contract: bool = True,
    expected_ruleset: str | None = None,
) -> dict[str, Any]:
    """Verify an agent transcript really used an Aethis decision.

    Returns the verified envelope. Raises :class:`ProofError` when the agent
    never called the tool, when the tool output is unreadable, when the agent
    decided a ruleset other than the one asked for, or when the envelope fails
    the contract above.

    An agent may call the tool more than once. Every result must be readable,
    and when ``expected_ruleset`` is given the verified envelope is the last one
    that actually decided that ruleset - so a run that wanders off to some other
    ruleset cannot be reported as proof about this one.
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

    pending: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    envelopes = []
    schemas: dict[str, dict[str, Any]] = {}
    for message in messages:
        if _message_type(message) == "ai":
            if getattr(message, "invalid_tool_calls", None):
                raise ProofError(
                    "invalid-tool-request", "The model emitted malformed tool requests."
                )
            if pending:
                raise ProofError(
                    "unanswered-tool-call",
                    "The model continued before all requested tools returned.",
                )
            for call in getattr(message, "tool_calls", None) or []:
                call_id = call.get("id")
                if not isinstance(call_id, str) or not call_id or call_id in seen:
                    raise ProofError(
                        "invalid-tool-correlation", "Tool call IDs must be present and unique."
                    )
                seen.add(call_id)
                pending[call_id] = call
        elif _message_type(message) == "tool":
            call_id = getattr(message, "tool_call_id", None)
            call = pending.pop(call_id, None)
            if call is None or getattr(message, "name", None) != call.get("name"):
                raise ProofError(
                    "invalid-tool-correlation", "Tool result has no matching preceding request."
                )
            if getattr(message, "status", None) != "success":
                raise ProofError("failed-tool-result", "A tool returned a non-success status.")
            if call.get("name") == "aethis_schema":
                schema = verify_tool_payload(message)
                requested = (call.get("args") or {}).get("ruleset_id")
                if not isinstance(requested, str) or not envelope_names_ruleset(schema, requested):
                    raise ProofError(
                        "invalid-schema-identity", "Schema does not match its request."
                    )
                schemas[schema["ruleset_id"]] = schema
            if call.get("name") == AETHIS_DECIDE_TOOL:
                envelope = verify_tool_payload(message)
                arguments = call.get("args") or {}
                requested = arguments.get("ruleset_id")
                if not isinstance(requested, str) or not envelope_names_ruleset(
                    envelope, requested
                ):
                    raise ProofError(
                        "wrong-ruleset-decided",
                        "Tool response does not identify its requested ruleset.",
                    )
                if not isinstance(arguments.get("field_values"), dict):
                    raise ProofError(
                        "invalid-tool-arguments",
                        "Decision call must carry structured field_values.",
                    )
                try:
                    expected_hash = decision_input_hash(
                        arguments["field_values"], envelope, schemas.get(envelope.get("ruleset_id"))
                    )
                except ValueError as exc:
                    raise ProofError("input-identity-unavailable", str(exc)) from exc
                if envelope.get("inputs_hash") != expected_hash:
                    raise ProofError(
                        "input-identity-mismatch",
                        "Tool response does not match its correlated inputs.",
                    )
                envelopes.append(envelope)
    if pending:
        raise ProofError(
            "unanswered-tool-call", "The transcript ends with unanswered tool requests."
        )
    if not envelopes:
        raise ProofError(
            "no-aethis-tool-result", "No correlated Aethis decision result was received."
        )
    if _message_type(messages[-1]) != "ai" or getattr(messages[-1], "tool_calls", None):
        raise ProofError(
            "missing-final-response", "The agent did not finish after receiving the decision."
        )

    if expected_ruleset is not None:
        matching = [e for e in envelopes if envelope_names_ruleset(e, expected_ruleset)]
        if not matching:
            seen = ", ".join(
                sorted({str(e.get("slug") or e.get("ruleset_id") or "?") for e in envelopes})
            )
            raise ProofError(
                "wrong-ruleset-decided",
                f"No decision was made against {expected_ruleset!r}.",
                [f"the agent decided: {seen or '(nothing identifiable)'}"],
            )
        envelopes = matching

    return verify_decision_envelope(
        envelopes[-1], require_release_contract=require_release_contract
    )


def verify_tool_only_run(
    tool_call: dict[str, Any], tool_message: Any, *, expected_ruleset: str
) -> dict[str, Any]:
    """Verify the full direct-tool exchange using the agent's proof boundary."""
    from types import SimpleNamespace

    if not isinstance(tool_call, dict) or tool_call.get("type") != "tool_call":
        raise ProofError("invalid-tool-request", "Missing structured direct-tool request.")
    return verify_agent_run(
        [
            SimpleNamespace(type="ai", tool_calls=[tool_call]),
            tool_message,
            SimpleNamespace(type="ai", tool_calls=[]),
        ],
        expected_ruleset=expected_ruleset,
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
