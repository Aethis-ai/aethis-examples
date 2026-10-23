#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Verify that every showcased ruleset is provenance-complete, and say so in
a form a release gate can read.

What "provenance-complete" means here is deliberately narrow, because the
public claim it supports is narrow: for a showcase to be traceable to its
source, **every criterion the published ruleset evaluates** must be bound to a
specific passage of a named authority, that passage must actually occur in the
document, and the document must be fetchable over a safe HTTPS target, under a
licence that permits reproducing it, at a digest that pins the version. A
citation key that points at nothing, a URL that merely resolves, or a quote
that has drifted from the text all fail.

The denominator is read from the **live engine**, not from anything committed
here. `/explain` is anonymous, so there is no reason to trust a file for this:
a snapshot in the repository is editable, and a denominator that can be edited
is a convention rather than a guarantee. The committed fixtures are a cache for
offline runs, and the gate diffs them against the live response and fails on
any drift. A criterion with no citation is a failure, never a smaller total.

Two coverage numbers are reported, and they are not the same thing:

``manifest_coverage``
    criteria bound to a verified citation, over participating criteria. This
    is what this repository controls, and it must be 100%.

``served_coverage``
    criteria whose live `/explain` and `/decide` explanations both carry
    complete, identical resolved references matching verified manifest targets,
    over participating criteria. Both owning envelopes must be observed with
    HTTP 200. Without both it is
    reported as ``null`` and the showcase cannot be claim-eligible - an
    unverified number must not be able to authorise a public claim.

A public surface may claim traceability for a showcase only when both are
100%. That combined condition is emitted per showcase as ``claim_eligible``,
so the claim on the surface and the evidence behind it cannot drift apart.

Usage:
    uv run provenance/check_provenance.py                  # live denominator + citations
    uv run provenance/check_provenance.py --offline        # structure only, nothing claimable
    uv run provenance/check_provenance.py --refresh-digests
    uv run provenance/check_provenance.py --refresh-fixtures
    uv run provenance/check_provenance.py --json evidence.json
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import math
import re
import json
import sys
import urllib.request
import urllib.error
from urllib.parse import quote as pct
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "provenance"))

from lib.fetching import FetchedSource, fetch_source, read_complete_response  # noqa: E402
from lib.json_decode import decode_json, validate_json_tree  # noqa: E402
from lib.manifest import ALLOWED_LICENCES, ManifestError, ShowcaseManifest, load_registry  # noqa: E402
from lib.quote_match import (  # noqa: E402
    MEDIA_PDF,
    Quote,
    build_deep_link,
    find_pdf_quote_page,
    normalise_ws,
    quote_occurs,
)
from lib.target_safety import TargetSafetyError, validate_target_url  # noqa: E402

DEFAULT_EVIDENCE = ROOT / "provenance" / "evidence" / "coverage.json"
# A partial run writes here instead, so a --showcase invocation can never leave
# a whole-surface artefact describing one showcase.
PARTIAL_EVIDENCE = ROOT / "provenance" / "evidence" / "coverage.partial.json"
PROD_API = "https://api.aethis.ai"


def fetch_live_explain(slug: str, base_url: str) -> dict:
    """The live explanation for a slug.

    Anonymous by default - no credential is needed to read an explanation, and
    the denominator must not depend on holding one. ``AETHIS_API_KEY`` is used
    when present purely to sidestep the anonymous per-IP rate limit, which a
    four-showcase sweep can trip. It is a read; nothing here mutates.
    """
    import os
    from urllib.parse import quote as pct

    url = f"{base_url}/api/v1/public/rulesets/{pct(slug, safe='')}/explain"
    headers = {"User-Agent": "aethis-examples-provenance-check/1.0"}
    api_key = os.environ.get("AETHIS_API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.getcode() != 200:
            raise ValueError(f"expected complete HTTP 200 explanation, got {response.getcode()}")
        return decode_json(read_complete_response(response))


def build_evidence(manifests: List[ShowcaseManifest], *, offline: bool, base_url: str, transport: Optional[Callable[..., tuple[int, object]]] = None, source_fetcher: Optional[Callable[[str], FetchedSource]] = None) -> dict:
    """Run every check and assemble the evidence artefact.

    One implementation, used by both the gate and ``--verify-artefact``, so the
    two can never disagree about what a correct artefact looks like.
    """
    from lib.manifest import scan_corpus_documents

    exemptions = load_corpus_exemptions()
    corpus_findings: List[dict] = []
    corpus_failures: List[Failure] = []
    for finding in scan_corpus_documents(manifests, ROOT):
        exemption = _is_exempt(finding, exemptions)
        record = dict(finding, exempt=bool(exemption))
        if exemption:
            record["exemption_reason"] = exemption.get("reason")
            record["exemption_owner"] = exemption.get("owner")
        else:
            corpus_failures.append(
                Failure(
                    finding["showcase"],
                    "restricted_content_in_corpus",
                    (
                        f"{finding['path']}:{finding['line']} contains restricted subject matter "
                        f"({finding['phrase']!r}). This file is published. Remove the phrase, or record "
                        "an owned exemption in provenance/corpus-exemptions.yaml saying why it stays "
                        "and who is resolving it."
                    ),
                    path=finding["path"],
                    line=finding["line"],
                )
            )
        corpus_findings.append(record)

    rows = []
    for showcase in manifests:
        if offline:
            row = check_showcase(showcase, offline=True)
        else:
            observed = probe_showcase(showcase, base_url=base_url, fetcher=source_fetcher or fetch_source, transport=transport or _http_json)
            row = observed["checked_paths"].get("explain")
            if row is None:
                row = observed["checked_paths"].get("decide") or check_showcase(showcase, offline=True)
            row = {**row,
                "claim_eligible": observed["claim_eligible"],
                "criteria_served_by_engine": observed["criteria_with_served_references"],
                "served_coverage": 1.0 if observed["claim_eligible"] else None,
                "served_by_path": observed["served_by_path"],
                "requested_selector": observed["requested_selector"], "observations": observed["observations"],
                "explain_status": observed["explain_status"], "decide_status": observed["decide_status"],
                "failures": [{"showcase": showcase.name, **f} for f in (observed["failures"] or row["failures"])],
            }
        rows.append(row)

    failures = [f for row in rows for f in row["failures"]] + corpus_failures
    all_live = bool(rows) and all(r["denominator_source"] == "live" and r.get("explain_status") == 200 and r.get("decide_status") == 200 and all(v is not None for v in r.get("served_by_path", {}).values()) for r in rows)
    mode = "offline" if offline else ("verified" if all_live else "degraded")

    totals = {
        "criteria_total": sum(r["criteria_total"] for r in rows),
        "criteria_declaring_citations": sum(r["criteria_declaring_citations"] for r in rows),
        "criteria_with_verified_citations": (
            None
            if any(r["criteria_with_verified_citations"] is None for r in rows)
            else sum(r["criteria_with_verified_citations"] for r in rows)
        ),
        "criteria_served_by_engine": sum(r["criteria_served_by_engine"] or 0 for r in rows),
        "served_coverage_verified": all(r["served_coverage"] is not None for r in rows),
        "showcases_claim_eligible": sum(1 for r in rows if r["claim_eligible"]),
        "showcases_total": len(rows),
    }

    evidence = {
        "artefact": "aethis-examples launch-showcase provenance coverage",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "binding": _binding(manifests),
        "mode": mode,
        "denominator_base_url": None if offline else base_url,
        "totals": totals,
        "showcases": rows,
        "corpus_findings": corpus_findings,
        "failures": failures,
    }
    try:
        validate_json_tree(evidence)
    except json.JSONDecodeError:
        # Accepted route envelopes can exceed the same bounds when assembled.
        # Emit only scalar summaries; oversized observations are unavailable
        # for an artifact claim and must never leave a successful receipt.
        reason = "assembled_artifact_over_budget"
        rows = [{
            **{key: row[key] for key in (
                "showcase", "ruleset_slug", "criteria_total",
                "criteria_declaring_citations", "denominator_source",
            )},
            "criteria_with_verified_citations": None,
            "criteria_served_by_engine": None, "claim_eligible": False,
            "claim_blocked_by": reason,
            "failures": [{"showcase": row["showcase"], "reason_code": reason,
                          "message": "Complete evidence exceeds artifact bounds; observations omitted and claim withheld"}],
        } for row in rows]
        evidence.update(mode="degraded", showcases=rows, corpus_findings=[],
                        failures=[failure for row in rows for failure in row["failures"]])
        totals.update(criteria_with_verified_citations=None, criteria_served_by_engine=0,
                      served_coverage_verified=False, showcases_claim_eligible=0)
        validate_json_tree(evidence)
    return evidence



def load_corpus_exemptions() -> List[dict]:
    """Recorded, owned exemptions from the corpus sweep."""
    import yaml

    path = ROOT / "provenance" / "corpus-exemptions.yaml"
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    return list(raw.get("exemptions") or [])


def _is_exempt(finding: dict, exemptions: List[dict]) -> Optional[dict]:
    for exemption in exemptions:
        if exemption.get("path") != finding["path"]:
            continue
        if exemption.get("line") not in (None, finding["line"]):
            continue
        phrases = exemption.get("phrases")
        if phrases and finding["phrase"] not in phrases:
            continue
        return exemption
    return None


def _display_path(path: Path) -> str:
    """Repo-relative inside the tree, absolute outside. ``relative_to`` raises
    on an outside path, and doing that after the write turns success into a
    traceback."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


class Failure(dict):
    """One machine-readable reason the gate is red."""

    def __init__(self, showcase: str, reason_code: str, message: str, **extra):
        super().__init__(showcase=showcase, reason_code=reason_code, message=message, **extra)


def _check_local_copies(manifest: ShowcaseManifest, failures: List[Failure]) -> None:
    """A self-cited document must match the bytes actually being cited.

    Three showcases cite documents this repository publishes. The citation
    points at the published mirror, but the file lives here, and the two can
    part company - an edit lands locally and the pinned digest still matches
    the older published copy, so the gate stays green while the text the rules
    were authored against has changed. Comparing the local bytes to the pin
    closes that gap in both directions.
    """
    for doc in manifest.documents.values():
        if not doc.local_path or not doc.expected_digest:
            continue
        path = ROOT / doc.local_path
        if not path.is_file():
            failures.append(
                Failure(
                    manifest.name,
                    "local_copy_missing",
                    f"document {doc.doc_id!r} names local_path {doc.local_path!r}, which does not exist",
                    document=doc.doc_id,
                )
            )
            continue
        local_digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if local_digest != doc.expected_digest:
            failures.append(
                Failure(
                    manifest.name,
                    "local_copy_diverged",
                    (
                        f"document {doc.doc_id!r} is cited at {doc.expected_digest} but the copy in "
                        f"this repository ({doc.local_path}) digests to {local_digest}. Either the "
                        "local text changed and the citation now quotes a version nobody can read, "
                        "or the published mirror is stale. Resolve which, then re-pin."
                    ),
                    document=doc.doc_id,
                )
            )


def _read_source(fetcher: Callable[[str], FetchedSource], url: str) -> FetchedSource:
    """Normalize transport/read failures, preserving safety and code errors."""
    try:
        return fetcher(url)
    except (OSError, http.client.HTTPException) as exc:
        reason = "fetch_timeout" if isinstance(exc, TimeoutError) else "fetch_failure"
        raise TargetSafetyError(reason, f"{type(exc).__name__}: source transport/read failed") from exc


def _fetch_documents(
    manifest: ShowcaseManifest, failures: List[Failure],
    *, fetcher: Callable[[str], FetchedSource] | None = None,
) -> Dict[str, Optional[FetchedSource]]:
    """Fetch each cited document once. A fetch or safety failure is recorded
    against every citation that depends on it, not swallowed."""
    fetched: Dict[str, Optional[FetchedSource]] = {}
    for doc_id, doc in manifest.documents.items():
        try:
            source = _read_source(fetcher or fetch_source, doc.url)
        except TargetSafetyError as exc:
            failures.append(
                Failure(
                    manifest.name,
                    exc.reason_code,
                    f"document {doc_id!r}: {exc}",
                    document=doc_id,
                    url=doc.url,
                )
            )
            fetched[doc_id] = None
            continue

        if source.media_type != doc.media_type:
            failures.append(
                Failure(
                    manifest.name,
                    "media_type_mismatch",
                    (
                        f"document {doc_id!r} declares media_type {doc.media_type!r} but the "
                        f"target served {source.media_type!r}; the quote would be checked "
                        "against differently-processed text than the manifest assumes"
                    ),
                    document=doc_id,
                )
            )
            fetched[doc_id] = None
            continue

        if doc.expected_digest and doc.expected_digest != source.digest:
            failures.append(
                Failure(
                    manifest.name,
                    "digest_mismatch",
                    (
                        f"document {doc_id!r} was pinned at {doc.expected_digest} but now "
                        f"digests to {source.digest}. The cited text has changed under the "
                        "citation: re-read the passage, then re-pin."
                    ),
                    document=doc_id,
                )
            )
            fetched[doc_id] = None
            continue

        fetched[doc_id] = source
    return fetched


def _normalised_quote(value: object) -> dict | None:
    """Compare selectors using the same whitespace semantics as quote matching."""
    if not isinstance(value, dict) or not isinstance(value.get("exact"), str):
        return None
    result = {}
    for field in ("exact", "prefix", "suffix"):
        text = value.get(field)
        if text is not None and not isinstance(text, str):
            return None
        result[field] = normalise_ws(text) if text else None
    return result if result["exact"] else None


def _check_served_references(
    manifest: ShowcaseManifest,
    criteria: list[dict],
    resolved: dict[str, dict],
    failures: list[Failure],
) -> list[str]:
    """Count complete engine-resolved references that match verified targets."""
    served = []
    fields = (
        "title", "authority", "url", "locator", "licence", "media_type",
        "source_version", "source_date", "content_digest", "deep_link",
    )
    for criterion in criteria:
        criterion_id = criterion["criterion_id"]
        expected_keys = set(manifest.criteria.get(criterion_id, []))
        references = criterion.get("source_references")
        if not isinstance(references, list):
            references = []
        keys = [r.get("source_id") if isinstance(r, dict) else None for r in references]
        # Length also refuses duplicate entries, even if their unique keys match.
        if (
            not expected_keys or len(keys) != len(expected_keys)
            or any(not isinstance(k, str) for k in keys)
            or set(keys) != expected_keys
            or set(criterion.get("source_refs") or []) != expected_keys
        ):
            failures.append(Failure(
                manifest.name, "served_reference_set_mismatch",
                f"criterion {criterion_id!r} does not serve exactly its declared, mapped resolved references",
                criterion=criterion_id,
            ))
            continue
        valid = True
        for reference in references:
            key = reference["source_id"]
            expected = resolved[key]
            mismatched = [field for field in fields if reference.get(field) != expected.get(field)]
            if type(reference.get("schema_version")) is not int or reference["schema_version"] != 1:
                mismatched.append("schema_version")
            if reference.get("target_kind") not in (None, "url"):
                mismatched.append("target_kind")
            for field in ("artefact_project_id", "artefact_source_id"):
                value = reference.get(field)
                if value is not None and (not isinstance(value, str) or value):
                    mismatched.append(field)
            if "snapshot" in reference and reference["snapshot"] != expected["content_digest"]:
                mismatched.append("snapshot")
            if _normalised_quote(reference.get("quote")) != _normalised_quote(expected["quote"]):
                mismatched.append("quote")
            try:
                timestamp = datetime.fromisoformat(reference.get("verified_at", "").replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    mismatched.append("verified_at")
            except (AttributeError, TypeError, ValueError):
                mismatched.append("verified_at")
            if not expected["verified"]:
                mismatched.append("unverified_target")
            if mismatched:
                valid = False
                failures.append(Failure(
                    manifest.name, "served_reference_mismatch",
                    f"criterion {criterion_id!r} citation {key!r} differs from the verified target: {', '.join(mismatched)}",
                    criterion=criterion_id, citation_key=key, fields=mismatched,
                ))
        if valid:
            served.append(criterion_id)
    return served


def check_showcase(
    manifest: ShowcaseManifest,
    *,
    offline: bool,
    live_explain: Optional[dict] = None,
    live_error: Optional[str] = None,
    candidate_explain: dict | None = None,
    source_fetcher: Callable[[str], FetchedSource] | None = None,
) -> dict:
    """Verify one showcase and return its evidence row.

    This single-path helper never authorizes a broad decision claim.
    ``served_path_eligible`` is consumed by the observed two-path verifier;
    ``claim_eligible`` remains false here.

    ``live_explain`` is the engine's own answer to "what does this ruleset
    evaluate, and what does it serve". When present it is authoritative for
    both the denominator and served coverage, and the committed fixture is
    diffed against it. ``candidate_explain`` instead grades an unpublished
    candidate for publish preflight; it never supplies served coverage or
    claim eligibility. Offline runs likewise cannot verify served references.
    Without live verified references, the showcase cannot be claim-eligible.
    """
    if live_explain is not None and candidate_explain is not None:
        raise ValueError("supply either live_explain or candidate_explain, not both")
    explanation = live_explain if live_explain is not None else candidate_explain
    failures: List[Failure] = []
    if explanation is not None and _criteria_of(explanation, path="explain") is None:
        failures.append(Failure(manifest.name, "malformed_criteria", "explanation carries malformed criterion objects or declarations"))
        explanation = None
        live_explain = None
        candidate_explain = None

    fixture_criteria = manifest.fixture_criteria()

    if live_error is not None:
        failures.append(
            Failure(
                manifest.name,
                "live_denominator_unavailable",
                (
                    f"could not read the live explanation for {manifest.ruleset_slug!r}: {live_error}. "
                    "The denominator must come from the engine; refusing to certify against a "
                    "committed snapshot alone."
                ),
            )
        )

    if explanation is not None:
        live_criteria = [c["criterion_id"] for c in explanation.get("criteria", [])]
        live_declared = {
            c["criterion_id"]: list(c.get("source_refs") or []) for c in explanation.get("criteria", [])
        }
        denominator_source = "live" if live_explain is not None else "candidate"
        # The fixture is a cache. If it disagrees with the engine it is stale or
        # edited, and either way every number derived from it is suspect.
        if sorted(live_criteria) != sorted(fixture_criteria):
            only_live = sorted(set(live_criteria) - set(fixture_criteria))
            only_fixture = sorted(set(fixture_criteria) - set(live_criteria))
            failures.append(
                Failure(
                    manifest.name,
                    "fixture_drift",
                    (
                        f"the committed explanation fixture disagrees with the {denominator_source} explanation "
                        f"(only live: {only_live}; only fixture: {only_fixture}). Re-capture with "
                        "--refresh-fixtures, and check whether the ruleset changed or the file was edited."
                    ),
                )
            )
        participating = live_criteria
        engine_declared = live_declared
    else:
        participating = fixture_criteria
        engine_declared = manifest.fixture_declared_keys()
        denominator_source = "fixture (unverified)"

    if not participating:
        failures.append(
            Failure(
                manifest.name,
                "empty_denominator",
                "the ruleset reports no criteria; refusing to certify a showcase with nothing in it",
            )
        )

    # Denominator integrity. A criterion the engine evaluates but the manifest
    # does not cite is the failure this whole gate exists to catch.
    uncited = [c for c in participating if c not in manifest.criteria]
    for criterion_id in uncited:
        failures.append(
            Failure(
                manifest.name,
                "uncited_criterion",
                (
                    f"criterion {criterion_id!r} is evaluated by the published ruleset but "
                    "carries no citation key. Every participating criterion must cite a "
                    "specific passage; the denominator cannot be reduced by omission."
                ),
                criterion=criterion_id,
            )
        )

    # The mirror-image drift: a manifest entry for a criterion that no longer
    # exists means the fixture and the manifest have parted company.
    stale = [c for c in manifest.criteria if c not in participating]
    for criterion_id in stale:
        failures.append(
            Failure(
                manifest.name,
                "stale_criterion",
                (
                    f"the manifest cites criterion {criterion_id!r}, which the published "
                    "ruleset no longer evaluates. Refresh the fixture and re-map."
                ),
                criterion=criterion_id,
            )
        )

    # Where the ruleset does declare citation keys, the manifest must be
    # describing the same citations - not a parallel set that happens to be the
    # right size.
    for criterion_id, declared in engine_declared.items():
        if not declared:
            continue
        mapped = set(manifest.criteria.get(criterion_id, []))
        if set(declared) != mapped:
            failures.append(
                Failure(
                    manifest.name,
                    "citation_key_mismatch",
                    (
                        f"criterion {criterion_id!r} declares citation keys {sorted(declared)} but the "
                        f"manifest maps {sorted(mapped)}. The publish payload is keyed by the declared "
                        "keys, so a mismatch means the targets would not resolve."
                    ),
                    criterion=criterion_id,
                )
            )

    _check_local_copies(manifest, failures)

    for doc in manifest.documents.values():
        if not doc.expected_digest:
            failures.append(
                Failure(
                    manifest.name,
                    "unpinned_document",
                    (
                        f"document {doc.doc_id!r} has no expected_digest. A citation with no "
                        "digest is not version-bound: the text it rests on could change "
                        "without the citation noticing. Pin it with --refresh-digests after "
                        "reading the passage."
                    ),
                    document=doc.doc_id,
                )
            )

    fetched: Dict[str, Optional[FetchedSource]] = {}
    if not offline:
        fetched = _fetch_documents(manifest, failures, fetcher=source_fetcher)

    resolved: Dict[str, dict] = {}
    for key, ref in manifest.references.items():
        doc = manifest.documents[ref.document]
        row = {
            "source_id": key,
            "title": doc.title,
            "authority": doc.authority,
            "url": doc.url,
            "locator": ref.locator,
            "licence": doc.licence,
            "media_type": doc.media_type,
            "source_version": doc.source_version,
            "source_date": doc.source_date,
            "content_digest": doc.expected_digest,
            "quote": ref.quote.as_wire(),
            "verified": False,
        }
        if offline:
            resolved[key] = row
            continue

        source = fetched.get(ref.document)
        if source is None:
            failures.append(
                Failure(
                    manifest.name,
                    "unverifiable_reference",
                    f"citation {key!r} could not be verified: its document failed to resolve",
                    citation_key=key,
                )
            )
            resolved[key] = row
            continue

        if not quote_occurs(ref.quote, source.content, source.media_type):
            failures.append(
                Failure(
                    manifest.name,
                    "quote_not_found",
                    (
                        f"the quote for {key!r} does not occur in the fetched source. Quotes "
                        "must be exact text from the document, never a summary or paraphrase."
                    ),
                    citation_key=key,
                )
            )
            resolved[key] = row
            continue

        pdf_page = find_pdf_quote_page(source.content, ref.quote) if source.media_type == MEDIA_PDF else None
        row["url"] = source.url
        row["content_digest"] = source.digest
        row["deep_link"] = build_deep_link(source.url, ref.quote, source.media_type, ref.locator, pdf_page)
        row["verified"] = True
        resolved[key] = row

    verified_keys = {k for k, row in resolved.items() if row["verified"]}
    # Offline, nothing was fetched, digested or quote-checked. There is a count
    # of criteria that *declare* a citation, and that is a different and much
    # weaker fact - so the verified count does not exist rather than silently
    # borrowing the declared one. A consumer rendering "30/30 verified" from a
    # run that verified nothing is the failure this avoids.
    criteria_declaring_citations = [c for c in participating if manifest.criteria.get(c)]
    criteria_with_citations = (
        None
        if offline
        else [c for c in participating if any(k in verified_keys for k in manifest.criteria.get(c, []))]
    )

    total = len(participating)
    manifest_coverage = (
        None if criteria_with_citations is None else ((len(criteria_with_citations) / total) if total else 0.0)
    )

    if live_explain is None or offline:
        # No verified live answer means no honest statement about what a visitor
        # receives. Reporting zero would read as "verified none"; reporting a
        # number from the snapshot would be worse.
        served: Optional[List[str]] = None
        served_coverage: Optional[float] = None
        claim_eligible = False
    else:
        served = _check_served_references(
            manifest, live_explain.get("criteria", []), resolved, failures
        )
        served_coverage = (len(served) / total) if total else 0.0
        claim_eligible = (
            bool(total)
            and manifest_coverage == 1.0
            and served_coverage == 1.0
            and not failures
        )

    return {
        "showcase": manifest.name,
        "ruleset_slug": manifest.ruleset_slug,
        "surface": manifest.surface,
        "criteria_total": total,
        "criteria_declaring_citations": len(criteria_declaring_citations),
        "criteria_with_verified_citations": None if criteria_with_citations is None else len(criteria_with_citations),
        "manifest_coverage": None if manifest_coverage is None else round(manifest_coverage, 4),
        "denominator_source": denominator_source,
        "criteria_served_by_engine": None if served is None else len(served),
        "served_coverage": None if served_coverage is None else round(served_coverage, 4),
        "served_path_eligible": claim_eligible,
        "claim_eligible": False,
        "claim_blocked_by": manifest.claim_blocked_by,
        "references_total": len(manifest.references),
        "references_verified": len(verified_keys),
        "broken_references": len(manifest.references) - len(verified_keys) if not offline else None,
        "documents": [
            {
                "document": d.doc_id,
                "url": d.url,
                "authority": d.authority,
                "licence": d.licence,
                "media_type": d.media_type,
                "source_version": d.source_version,
                "source_date": d.source_date,
                "expected_digest": d.expected_digest,
            }
            for d in manifest.documents.values()
        ],
        "references": list(resolved.values()),
        "failures": list(failures),
    }


def _git_commit() -> Optional[str]:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001 - absent git is not a gate failure
        return None


def _binding(manifests: List[ShowcaseManifest]) -> dict:
    """What this artefact was computed from: tree, fixtures, engine identity.

    The fixture digests matter most. They are the inputs a consumer cannot see,
    and the thing a forger would have to keep consistent.
    """
    fixtures = {}
    for showcase in manifests:
        try:
            raw = showcase.explain_fixture.read_bytes()
        except OSError:
            continue
        fixtures[str(showcase.explain_fixture.relative_to(ROOT))] = (
            "sha256:" + hashlib.sha256(raw).hexdigest()
        )
    return {
        "commit": _git_commit(),
        "fixture_digests": fixtures,
        "manifest_digests": {
            str(m.manifest_path.relative_to(ROOT)): "sha256:"
            + hashlib.sha256(m.manifest_path.read_bytes()).hexdigest()
            for m in manifests
        },
    }


# Fields that differ between two honest runs of the same tree, and therefore
# cannot be part of an equality check:
#
#   generated_at   - wall clock, different by construction.
#   binding.commit - the CHECKOUT commit. In a pull-request build that is the
#                    ephemeral merge commit, never the branch head the artefact
#                    was committed on, so it can never match.
#
# They stay in the artefact, because "when, and from what tree" is exactly the
# provenance an artefact should carry. They are simply not gated on. Everything
# else - coverage numbers, denominators, mode, per-showcase eligibility,
# fixture and manifest digests, corpus findings, failures - is compared
# exactly, so a forged number still fails.
VOLATILE_TOP_LEVEL = ("generated_at",)
VOLATILE_BINDING = ("commit",)


REQUEST_TIMEOUT = 30.0
REQUIRED_REFERENCE_FIELDS = (
    "schema_version",
    "source_id",
    "title",
    "authority",
    "url",
    "content_digest",
    "licence",
    "verified_at",
    "quote",
    "media_type",
    "deep_link",
)
SUPPORTED_SCHEMA_VERSIONS = (1,)


def _http_json(url: str, *, method: str = "GET", body: Optional[dict] = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    import os
    headers = {"User-Agent": "aethis-examples-provenance-probe/1.0"}
    if os.environ.get("AETHIS_API_KEY"):
        headers["X-API-Key"] = os.environ["AETHIS_API_KEY"]
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return response.status, decode_json(read_complete_response(response))
    except urllib.error.HTTPError as exc:
        raw = read_complete_response(exc).decode("utf-8", errors="replace")
        try:
            return exc.code, decode_json(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def check_reference(
    ref: dict,
    *,
    where: str,
    fetcher: Callable[[str], object],
    failures: List[dict],
) -> None:
    """Validate one served reference as hard as a reader could."""
    if not isinstance(ref, dict):
        failures.append({"reason_code": "malformed_reference", "where": where, "message": "resolved source reference must be an object"})
        return
    if not isinstance(ref.get("quote"), dict) or not isinstance(ref["quote"].get("exact"), str) or any(ref["quote"].get(k) is not None and not isinstance(ref["quote"][k], str) for k in ("exact", "prefix", "suffix")):
        failures.append({"reason_code": "malformed_reference", "where": where, "message": "resolved reference quote must carry typed text selectors"})
        return
    if any(k in ref and not isinstance(ref[k], str) for k in ("source_id", "title", "authority", "url", "content_digest", "licence", "verified_at", "media_type", "deep_link")):
        failures.append({"reason_code": "malformed_reference", "where": where, "message": "resolved reference metadata must be text"})
        return
    if any(ref.get(k) is not None and not isinstance(ref[k], str) for k in ("locator", "source_version", "source_date", "snapshot", "target_kind", "artefact_project_id", "artefact_source_id")):
        failures.append({"reason_code": "malformed_reference", "where": where, "message": "optional resolved reference metadata must be text"})
        return
    missing = [f for f in REQUIRED_REFERENCE_FIELDS if f not in ref or ref[f] in (None, "")]
    if missing:
        failures.append(
            {
                "reason_code": "reference_missing_fields",
                "where": where,
                "message": f"served reference is missing required field(s): {', '.join(missing)}",
            }
        )
        return

    if ref["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        failures.append(
            {
                "reason_code": "unsupported_schema_version",
                "where": where,
                "message": (
                    f"reference declares schema_version {ref['schema_version']!r}; this probe "
                    f"understands {SUPPORTED_SCHEMA_VERSIONS}. Refusing to certify a contract "
                    "it cannot read."
                ),
            }
        )
        return

    digest = str(ref["content_digest"])
    if not (digest.startswith("sha256:") and len(digest) == 71):
        failures.append(
            {
                "reason_code": "malformed_digest",
                "where": where,
                "message": f"content_digest {digest!r} is not 'sha256:<64 hex chars>'",
            }
        )
        return

    if ref["licence"] not in ALLOWED_LICENCES:
        failures.append(
            {
                "reason_code": "unallowed_licence",
                "where": where,
                "message": (
                    f"reference reproduces text under licence {ref['licence']!r}, which is not "
                    "on the allowlist for public reproduction"
                ),
            }
        )

    try:
        validate_target_url(str(ref["url"]))
    except TargetSafetyError as exc:
        failures.append(
            {
                "reason_code": exc.reason_code,
                "where": where,
                "message": f"served target {ref['url']!r} is unsafe: {exc}",
            }
        )
        return

    quote = Quote(
        exact=str(ref["quote"].get("exact", "")),
        prefix=ref["quote"].get("prefix"),
        suffix=ref["quote"].get("suffix"),
    )
    if not quote.exact:
        failures.append(
            {"reason_code": "empty_quote", "where": where, "message": "reference carries no quoted text"}
        )
        return

    try:
        source = _read_source(fetcher, str(ref["url"]))
    except TargetSafetyError as exc:
        failures.append({"reason_code": exc.reason_code, "where": where, "message": str(exc)})
        return

    if source.digest != digest:  # type: ignore[attr-defined]
        failures.append(
            {
                "reason_code": "digest_mismatch",
                "where": where,
                "message": (
                    f"the served reference claims digest {digest}, but the target now digests to "
                    f"{source.digest}. The citation is no longer bound to the text it was "  # type: ignore[attr-defined]
                    "verified against."
                ),
            }
        )
        return

    if not quote_occurs(quote, source.content, source.media_type):  # type: ignore[attr-defined]
        failures.append(
            {
                "reason_code": "quote_not_found",
                "where": where,
                "message": (
                    "the quoted passage does not occur in the digested source. A citation that "
                    "paraphrases is not a citation."
                ),
            }
        )
        return

    pdf_page = (
        find_pdf_quote_page(source.content, quote)  # type: ignore[attr-defined]
        if source.media_type == MEDIA_PDF  # type: ignore[attr-defined]
        else None
    )
    expected_link = build_deep_link(
        source.url,  # type: ignore[attr-defined]
        quote,
        source.media_type,  # type: ignore[attr-defined]
        ref.get("locator"),
        pdf_page,
    )
    if ref["deep_link"] != expected_link:
        failures.append(
            {
                "reason_code": "deep_link_mismatch",
                "where": where,
                "message": (
                    f"served deep_link does not locate the quote. served={ref['deep_link']!r} "
                    f"expected={expected_link!r}"
                ),
            }
        )


def _criteria_of(payload: object, *, path: str) -> Optional[List[dict]]:
    """Read only the owning route envelope and typed criterion declarations."""
    if not isinstance(payload, dict):
        return None
    if path == "explain":
        criteria = payload.get("criteria")
    elif path == "decide" and "criteria" not in payload:
        explanation = payload.get("explanation")
        if not isinstance(explanation, dict) or not isinstance(explanation.get("groups"), list):
            return None
        criteria = []
        for group in explanation["groups"]:
            if not isinstance(group, dict) or not isinstance(group.get("criteria"), list):
                return None
            criteria.extend(group["criteria"])
    else:
        return None
    if not isinstance(criteria, list):
        return None
    identifiers = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            return None
        identifier = criterion.get("criterion_id")
        keys = criterion.get("source_refs", [])
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            return None
        if not isinstance(keys, list) or any(not isinstance(k, str) or not k for k in keys):
            return None
        identifiers.add(identifier)
    return list(criteria)


def _references_by_criterion(criteria: Optional[List[dict]]) -> Dict[str, List[dict]]:
    return {c["criterion_id"]: c.get("source_references") if isinstance(c.get("source_references"), list) else [] for c in (criteria or [])}


class ObservationError(ValueError):
    """Expected unsupported wire observation, rather than a code error."""


IDENTITY_FIELDS = ("ruleset_id", "slug", "ruleset_version", "content_digest")
VALID_DECISIONS = ("eligible", "not_eligible", "undetermined")


def _observed_identity(payload: object, *, selector: str, path: str, failures: List[dict]) -> Optional[dict]:
    """Bind a selector to resolved producer identity; aliases are not IDs."""
    identity = {k: payload.get(k) for k in IDENTITY_FIELDS} if isinstance(payload, dict) else {}
    rid, slug, version, digest = (identity.get(k) for k in IDENTITY_FIELDS)
    valid = (
        isinstance(selector, str) and bool(selector)
        and isinstance(rid, str) and bool(rid) and rid != slug
        and (slug is None or isinstance(slug, str) and bool(slug))
        and selector in (rid, slug)
        and isinstance(version, str) and bool(version) and version != "unknown"
        and isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None
    )
    if not valid:
        failures.append({"reason_code": "response_identity", "where": f"{selector}/{path}", "message": "response must resolve the requested selector to a distinct ruleset ID, published version and content digest"})
        return None
    return identity


def _nonnegative_json_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def route_contract_problems(payload: object, *, path: str) -> List[str]:
    """Minimal consumed contract from the real leaf DTO and layered builder.

    This verifier always sends empty field_values; it does not claim to verify
    arbitrary-input decision or rulebook contracts.
    """
    if not isinstance(payload, dict):
        return ["owning route response must be an object"]
    criteria = _criteria_of(payload, path=path)
    if criteria is None:
        return ["owning criterion declarations are missing or malformed"]
    problems = []
    if path == "explain":
        if any(not isinstance(c.get("rule_text"), str) for c in criteria):
            problems.append("explain criteria require text rule_text")
        if any(c.get(k) is not None and not isinstance(c[k], str) for c in criteria for k in ("title", "group")):
            problems.append("optional explain criterion labels must be text")
        return problems
    for field in ("decision_id", "engine_version"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            problems.append(f"decide requires text {field}")
    if not isinstance(payload.get("decision_id"), str) or re.fullmatch(r"dec_[A-Za-z0-9_-]{16}", payload["decision_id"]) is None:
        problems.append("decision_id must match the producer invocation handle format")
    if not isinstance(payload.get("engine_version"), str) or re.fullmatch(r"aethis-core@\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", payload["engine_version"]) is None:
        problems.append("engine_version must match the product-prefixed producer version")
    timestamp = payload.get("decision_time")
    try:
        if not isinstance(timestamp, str):
            raise ValueError("missing timestamp")
        if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("timestamp lacks zone")
    except ValueError:
        problems.append("decide requires ISO decision_time")
    for field in ("fields_evaluated", "fields_provided"):
        if type(payload.get(field)) is not int or payload[field] < 0:
            problems.append(f"decide requires nonnegative integer {field}")
    if payload.get("fields_provided") != 0:
        problems.append("fields_provided must match the empty request")
    if payload.get("inputs_hash") != "sha256:" + hashlib.sha256(b"{}").hexdigest():
        problems.append("inputs_hash must bind the actual empty request")
    if payload.get("rulebook_id") is not None or payload.get("release") is not None:
        problems.append("leaf response must not claim a rulebook/release identity")
    if payload.get("content_identity") != payload.get("content_digest"):
        problems.append("leaf content_identity must equal content_digest")
    decision = payload.get("decision")
    if decision not in VALID_DECISIONS:
        problems.append("decide requires eligible, not_eligible or undetermined")
    errors = payload.get("field_errors")
    if errors is not None and (not isinstance(errors, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in errors.items())):
        problems.append("field_errors must be a text mapping or null")
    if errors and decision != "undetermined":
        problems.append("blocking field_errors forbid a terminal decision")
    timing = payload.get("timing")
    if timing is not None:
        if not isinstance(timing, dict) or not _nonnegative_json_number(timing.get("total_ms")) or any(timing.get(k) is not None and not _nonnegative_json_number(timing[k]) for k in ("compilation_ms", "evaluation_ms")) or any(k in timing and type(timing[k]) is not bool for k in ("cache_hit", "ruleset_cache_hit")):
            problems.append("optional timing must match the producer timing DTO")
    explanation = payload["explanation"]
    nested_decision = explanation.get("decision")
    if nested_decision not in ("eligible", "not_eligible", "pending"):
        problems.append("layered explanation requires its builder decision label")
    if decision in ("eligible", "not_eligible") and nested_decision != decision:
        problems.append("terminal decision contradicts its layered explanation")
    if decision == "undetermined" and nested_decision in ("eligible", "not_eligible") and not errors:
        problems.append("undetermined decision requires pending explanation or blocking field_errors")
    unused = explanation.get("unused_facts")
    if not isinstance(unused, list) or any(not isinstance(k, str) for k in unused):
        problems.append("layered explanation requires unused_facts text list")
    statuses = ("satisfied", "not_satisfied", "pending")
    if any(not isinstance(g.get("group"), str) or g.get("status") not in statuses for g in explanation["groups"]):
        problems.append("layered groups require text group and supported status")
    if any(c.get("status") not in statuses or not isinstance(c.get("title"), str) for c in criteria):
        problems.append("layered criteria require title and supported status")
    return problems


def pair_contract_problems(selector: str, explain: object, decide: object) -> List[dict]:
    failures: List[dict] = []
    identities = {
        "explain": _observed_identity(explain, selector=selector, path="explain", failures=failures),
        "decide": _observed_identity(decide, selector=selector, path="decide", failures=failures),
    }
    if all(identities.values()) and identities["explain"] != identities["decide"]:
        failures.append({"reason_code": "identity_divergence", "where": selector, "message": "owning responses resolve different ruleset IDs, aliases, versions or content digests"})
    decision = decide.get("decision") if isinstance(decide, dict) else None
    nested = decide.get("explanation") if isinstance(decide, dict) else None
    if decision not in VALID_DECISIONS or (decision in ("eligible", "not_eligible") and isinstance(nested, dict) and nested.get("decision") != decision):
        failures.append({"reason_code": "invalid_decision", "where": selector, "message": "unsupported decision or contradictory terminal layered result"})
    for name, payload in (("explain", explain), ("decide", decide)):
        problems = route_contract_problems(payload, path=name)
        for problem in problems:
            failures.append({"reason_code": "response_contract", "where": f"{selector}/{name}", "message": problem})
    return failures


def probe_showcase(
    manifest: ShowcaseManifest,
    *,
    base_url: str,
    fetcher: Callable[[str], object],
    transport: Callable[..., tuple[int, dict]] = _http_json,
) -> dict:
    failures: List[dict] = []
    slug = manifest.ruleset_slug

    def observe(url: str, **kwargs: object) -> tuple[int, object]:
        try:
            result = transport(url, **kwargs)
            if not isinstance(result, tuple) or len(result) != 2 or type(result[0]) is not int:
                raise ObservationError("malformed HTTP observation")
            validate_json_tree(result[1])
            return result
        except (TargetSafetyError, ObservationError, OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeDecodeError) as exc:
            failures.append({"reason_code": "observation_unavailable", "where": url, "message": f"{type(exc).__name__}: owning path observation failed"})
            return 0, None
    explain_status, explain = observe(f"{base_url}/api/v1/public/rulesets/{pct(slug, safe='')}/explain")
    if explain_status != 200:
        failures.append(
            {
                "reason_code": "explain_status",
                "where": f"{slug} GET /explain",
                "message": f"expected HTTP 200, got {explain_status}: {json.dumps(explain)[:400]}",
            }
        )

    decide_status, decide = observe(
        f"{base_url}/api/v1/public/decide",
        method="POST",
        body={"ruleset_id": slug, "field_values": {}, "include_explanation": True},
    )
    if decide_status != 200:
        failures.append(
            {
                "reason_code": "decide_status",
                "where": f"{slug} POST /decide",
                "message": f"expected HTTP 200, got {decide_status}: {json.dumps(decide)[:400]}",
            }
        )

    failures.extend(pair_contract_problems(slug, explain, decide))
    observations = {
        name: {"http_status": status, "response": payload}
        for name, status, payload in (("explain", explain_status, explain), ("decide", decide_status, decide))
    }

    explain_criteria = _criteria_of(explain, path="explain") if explain_status == 200 else None
    decide_criteria = _criteria_of(decide, path="decide") if decide_status == 200 else None
    for name, criteria in (("explain", explain_criteria), ("decide", decide_criteria)):
        if criteria is None:
            failures.append(
                {
                    "reason_code": "missing_criteria",
                    "where": f"{slug} {name}",
                    "message": (
                        "response carries no criterion list in either supported shape; the "
                        "explanation contract is not being served"
                    ),
                }
            )

    explain_refs = _references_by_criterion(explain_criteria)
    decide_refs = _references_by_criterion(decide_criteria)

    # Share source verification and manifest comparison with the claim gate.
    # Cache within this probe so auditing both paths does not multiply reads.
    sources = {}
    source_errors = {}
    def cached_fetch(url: str) -> FetchedSource:
        if url in source_errors:
            raise source_errors[url]
        if url not in sources:
            try:
                sources[url] = _read_source(fetcher, url)
            except TargetSafetyError as exc:
                source_errors[url] = exc
                raise
        return sources[url]
    checked = {}
    for name, criteria in (("explain", explain_criteria), ("decide", decide_criteria)):
        if criteria is None:
            continue
        checked[name] = check_showcase(
            manifest, offline=False, live_explain={"criteria": criteria},
            source_fetcher=cached_fetch,
        )
        for failure in checked[name]["failures"]:
            failures.append({**failure, "where": f"{slug}/{name}/{failure.get('criterion', 'sources')}"})

    # Retain the omission check, but audit every live criterion as well.
    participating = sorted(set(manifest.fixture_criteria()) | set(explain_refs) | set(decide_refs))
    for criterion_id in participating:
        served = explain_refs.get(criterion_id)
        if served is None:
            failures.append(
                {
                    "reason_code": "criterion_absent",
                    "where": f"{slug}/{criterion_id}",
                    "message": "the fixture expects this criterion but the live explanation omits it",
                }
            )
            continue
        if not served:
            failures.append(
                {
                    "reason_code": "criterion_without_reference",
                    "where": f"{slug}/{criterion_id}",
                    "message": (
                        "criterion is evaluated but serves no source reference; the decision it "
                        "contributes to cannot be claimed traceable"
                    ),
                }
            )
            continue
        for ref in served:
            check_reference(ref, where=f"{slug}/{criterion_id}/{ref.get('source_id') if isinstance(ref, dict) else '<malformed>'}", fetcher=cached_fetch, failures=failures)

    # The two paths must be byte-identical, or a caller can be shown one
    # citation and audited against another.
    for criterion_id in participating:
        if explain_refs.get(criterion_id) != decide_refs.get(criterion_id):
            failures.append(
                {
                    "reason_code": "path_divergence",
                    "where": f"{slug}/{criterion_id}",
                    "message": "/explain and /decide serve different source references for this criterion",
                }
            )

    served_count = (
        checked.get("explain", {}).get("criteria_served_by_engine")
        if "explain" in checked and "decide" in checked and not failures else None
    )
    return {
        "showcase": manifest.name,
        "ruleset_slug": slug,
        "base_url": base_url,
        "criteria_total": len(explain_criteria) if explain_criteria is not None else None,
        "criteria_with_served_references": served_count,
        "served_by_path": {name: checked.get(name, {}).get("criteria_served_by_engine") for name in ("explain", "decide")},
        "checked_paths": checked,
        "requested_selector": slug, "observations": observations,
        "claim_eligible": bool(served_count) and all(checked.get(name, {}).get("served_path_eligible") is True for name in ("explain", "decide")) and not failures,
        "explain_status": explain_status,
        "decide_status": decide_status,
        "failures": failures,
    }


def substantive(artefact: dict) -> dict:
    """The part of an artefact that two honest runs must agree on exactly."""
    import copy as _copy

    validate_json_tree(artefact)
    view = _copy.deepcopy(artefact)
    for key in VOLATILE_TOP_LEVEL:
        view.pop(key, None)
    binding = view.get("binding")
    if isinstance(binding, dict):
        for key in VOLATILE_BINDING:
            binding.pop(key, None)
    for row in view.get("showcases", []):
        observations = row.get("observations", {})
        item = observations.get("decide") if isinstance(observations, dict) else None
        decide = item.get("response") if isinstance(item, dict) else None
        if isinstance(decide, dict):
            for key in ("decision_id", "decision_time", "timing"):
                decide.pop(key, None)
    return view


def _commit_is_ancestor(commit: Optional[str]) -> Optional[bool]:
    """Whether ``commit`` is reachable from HEAD. None when unknowable.

    Advisory only. A shallow clone, a detached HEAD or a fresh checkout can all
    make this unanswerable, and an unanswerable question must not fail a gate -
    that is how a check becomes something people route around.
    """
    import subprocess

    if not commit:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, "HEAD"],
            capture_output=True, timeout=10,
        )
    except Exception:  # noqa: BLE001
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def verify_artefact(manifests: List[ShowcaseManifest], path: Path, base_url: str, *, transport: Optional[Callable[..., tuple[int, object]]] = None, source_fetcher: Optional[Callable[[str], FetchedSource]] = None) -> int:
    """An artefact is valid iff re-running the gate reproduces it.

    Checking only the binding was not enough: a reviewer hand-set
    ``claim_eligible: true`` on every showcase, left the fixture digests alone,
    and the check passed - the forged fields were simply not among the ones
    being compared. Enumerating fields to protect is a losing game, so this
    recomputes the whole artefact and diffs it. Retained per-invocation decision
    ID/time/timing may move after both stored and fresh wire contracts validate.
    """
    if not path.is_file():
        print(f"FAIL  no evidence artefact at {path}", file=sys.stderr)
        return 1
    try:
        stored = decode_json(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        print("FAIL  evidence artefact could not be read or decoded", file=sys.stderr)
        return 1
    if not isinstance(stored, dict):
        print("FAIL  evidence artefact must be an object", file=sys.stderr)
        return 1

    if not isinstance(stored.get("showcases"), list) or not stored["showcases"] or any(not isinstance(row, dict) for row in stored["showcases"]):
        print("FAIL  evidence artefact requires showcase objects", file=sys.stderr)
        return 1

    fresh = build_evidence(manifests, offline=False, base_url=base_url, transport=transport, source_fetcher=source_fetcher)

    problems: List[str] = []
    for row in stored.get("showcases", []):
        observations = row.get("observations", {})
        if not isinstance(observations, dict) or any(not isinstance(observations.get(name), dict) or observations[name].get("http_status") != 200 for name in ("explain", "decide")):
            problems.append("stored artefact lacks complete owning observations")
            continue
        if pair_contract_problems(row.get("requested_selector"), observations["explain"].get("response"), observations["decide"].get("response")):
            problems.append("stored owning observations violate the producer contract")
    if fresh["failures"] or not all(r["claim_eligible"] for r in fresh["showcases"]):
        problems.append("fresh owning observations withhold the provenance claim")
    if stored.get("mode") != "verified":
        problems.append(
            f"artefact mode is {stored.get('mode')!r}; only a fully verified run may be committed. "
            "An offline run proves nothing was fetched, digested or quote-checked, and a degraded "
            "one means at least one denominator never came from the engine."
        )

    # A rejected wire contract is already a failed verification. Do not deeply
    # copy malformed retained responses merely to produce additional diffs.
    if not problems:
        comparable_stored = substantive(stored)
        comparable_fresh = substantive(fresh)
        if comparable_stored != comparable_fresh:
            for key in sorted(set(comparable_stored) | set(comparable_fresh)):
                if comparable_stored.get(key) != comparable_fresh.get(key):
                    problems.append(f"{key!r} differs from a fresh run")

    if problems:
        print("FAIL  the committed evidence artefact is not what this tree produces:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("  Regenerate it with: uv run provenance/check_provenance.py", file=sys.stderr)
        return 1
    recorded = (stored.get("binding") or {}).get("commit")
    ancestry = _commit_is_ancestor(recorded)
    note = ""
    if ancestry is False:
        # Reported, never fatal: a checkout that does not contain the recorded
        # commit is normal in a shallow CI clone.
        note = " - recorded commit is not reachable from HEAD (informational)"
    elif ancestry is None and recorded:
        note = " - recorded commit not resolvable in this checkout (informational)"
    print(
        "artefact reproduces exactly from this tree; every substantive field matches a fresh run "
        f"(recorded commit {recorded}{note})"
    )
    return 0


def refresh_digests(manifests: List[ShowcaseManifest]) -> int:
    """Fetch each document and write its digest back into the manifest.

    A convenience for authoring, never part of the gate: it is the human's job
    to have read the passage before pinning it.
    """
    import re

    changed = 0
    for manifest in manifests:
        text = manifest.manifest_path.read_text()
        for doc in manifest.documents.values():
            try:
                source = fetch_source(doc.url)
            except TargetSafetyError as exc:
                print(f"  ! {manifest.name}/{doc.doc_id}: {exc}", file=sys.stderr)
                continue
            if doc.expected_digest == source.digest:
                continue
            pattern = re.compile(
                rf"(^  {re.escape(doc.doc_id)}:\n(?:.*\n)*?    expected_digest:)[^\n]*$",
                re.MULTILINE,
            )
            new_text, n = pattern.subn(rf"\g<1> {source.digest}", text)
            if n != 1:
                print(
                    f"  ! {manifest.name}/{doc.doc_id}: could not locate expected_digest to update",
                    file=sys.stderr,
                )
                continue
            text = new_text
            changed += 1
            print(f"  pinned {manifest.name}/{doc.doc_id} -> {source.digest}")
        manifest.manifest_path.write_text(text)
    return changed


def refresh_fixtures(manifests: List[ShowcaseManifest], base_url: str) -> None:
    """Re-capture each showcase's explanation fixture from a live engine."""
    from urllib.parse import quote as pct

    for manifest in manifests:
        url = f"{base_url}/api/v1/public/rulesets/{pct(manifest.ruleset_slug, safe='')}/explain"
        request = urllib.request.Request(url, headers={"User-Agent": "aethis-examples-provenance-check/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = decode_json(read_complete_response(response))
        manifest.explain_fixture.write_text(json.dumps(payload, indent=4) + "\n")
        print(f"  refreshed {manifest.explain_fixture.relative_to(ROOT)} ({len(payload.get('criteria', []))} criteria)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="structural checks only; no network. Nothing can be claim-eligible in this mode.",
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_EVIDENCE, help="where to write the evidence artefact")
    parser.add_argument("--refresh-digests", action="store_true", help="re-pin every document digest, then exit")
    parser.add_argument("--refresh-fixtures", action="store_true", help="re-capture explanation fixtures, then exit")
    parser.add_argument("--base-url", default=PROD_API, help="engine to read explanation fixtures from")
    parser.add_argument("--showcase", action="append", help="limit to named showcase(s)")
    parser.add_argument(
        "--list-showcases",
        action="store_true",
        help="print showcase names, one per line, then exit (for scripting)",
    )
    parser.add_argument(
        "--verify-artefact",
        action="store_true",
        help="check the committed evidence artefact still describes this tree, then exit",
    )
    args = parser.parse_args()

    try:
        manifests = load_registry(ROOT)
    except ManifestError as exc:
        print(f"FAIL  manifest error: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.showcase:
        wanted = set(args.showcase)
        known = {m.name for m in manifests}
        unknown = sorted(wanted - known)
        if unknown:
            print(
                f"FAIL  unknown showcase(s) {unknown}; known: {', '.join(sorted(known))}",
                file=sys.stderr,
            )
            sys.exit(2)
        manifests = [m for m in manifests if m.name in wanted]
        # A subset run must not overwrite the committed evidence artefact, which
        # P10 reads as the coverage of the whole launch surface.
        if args.json == DEFAULT_EVIDENCE:
            args.json = PARTIAL_EVIDENCE

    if args.list_showcases:
        for showcase in manifests:
            print(showcase.name)
        return

    if args.verify_artefact:
        sys.exit(verify_artefact(manifests, args.json, args.base_url))

    if args.refresh_fixtures:
        refresh_fixtures(manifests, args.base_url)
        return
    if args.refresh_digests:
        refresh_digests(manifests)
        return

    # Sweep the corpus documents themselves. Checking only the quoted passages
    # left everything else in a source file unread, which is how a restricted
    # phrase reached the published mirror in a part of a document nobody had
    # quoted.
    from lib.manifest import scan_corpus_documents

    exemptions = load_corpus_exemptions()
    corpus_findings = []
    corpus_failures = []
    for finding in scan_corpus_documents(manifests, ROOT):
        exemption = _is_exempt(finding, exemptions)
        finding = dict(finding, exempt=bool(exemption))
        if exemption:
            finding["exemption_reason"] = exemption.get("reason")
            finding["exemption_owner"] = exemption.get("owner")
        else:
            corpus_failures.append(
                Failure(
                    finding["showcase"],
                    "restricted_content_in_corpus",
                    (
                        f"{finding['path']}:{finding['line']} contains restricted subject matter "
                        f"({finding['phrase']!r}). This file is published. Remove the phrase, or record "
                        "an owned exemption in provenance/corpus-exemptions.yaml saying why it stays "
                        "and who is resolving it."
                    ),
                    path=finding["path"],
                    line=finding["line"],
                )
            )
        corpus_findings.append(finding)

    evidence = build_evidence(manifests, offline=args.offline, base_url=args.base_url)
    rows = evidence["showcases"]
    corpus_findings = evidence["corpus_findings"]
    failures = evidence["failures"]
    totals = evidence["totals"]
    failures = [f for row in rows for f in row["failures"]] + corpus_failures

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(evidence, indent=2) + "\n")

    width = max(len(r["showcase"]) for r in rows)
    print(f"{'showcase'.ljust(width)}   cited/total   served/total   denominator   claim")
    for row in rows:
        cited = (
            f"{row['criteria_declaring_citations']}/{row['criteria_total']} decl"
            if row["criteria_with_verified_citations"] is None
            else f"{row['criteria_with_verified_citations']}/{row['criteria_total']}"
        )
        served = (
            "unverified"
            if row["criteria_served_by_engine"] is None
            else f"{row['criteria_served_by_engine']}/{row['criteria_total']}"
        )
        claim = "eligible" if row["claim_eligible"] else "WITHHELD"
        print(
            f"{row['showcase'].ljust(width)}   {cited.center(11)}   {served.center(12)}   "
            f"{row['denominator_source'].center(11)}   {claim}"
        )
    print()
    served_line = (
        f"served by the engine: {totals['criteria_served_by_engine']}/{totals['criteria_total']}"
        if totals["served_coverage_verified"]
        else "served by the engine: UNVERIFIED (no live response; nothing here may be claimed)"
    )
    verified_line = (
        f"citations verified: {totals['criteria_with_verified_citations']}/{totals['criteria_total']} criteria"
        if totals["criteria_with_verified_citations"] is not None
        else (
            f"citations verified: NONE - offline run, nothing was fetched, digested or quote-checked "
            f"({totals['criteria_declaring_citations']}/{totals['criteria_total']} criteria declare one)"
        )
    )
    print(verified_line + "; " + served_line)
    print(f"evidence: {_display_path(args.json)}")

    exempted = [f for f in corpus_findings if f.get("exempt")]
    if exempted:
        print()
        print(f"{len(exempted)} recorded corpus exemption(s) - reported, not resolved:")
        for finding in exempted:
            print(
                f"  - {finding['path']}:{finding['line']} ({finding['phrase']!r}), "
                f"owner: {finding.get('exemption_owner')}"
            )

    if failures:
        print()
        print(f"FAIL  {len(failures)} provenance failure(s):", file=sys.stderr)
        for failure in failures:
            print(f"  [{failure['showcase']}] {failure['reason_code']}: {failure['message']}", file=sys.stderr)
        sys.exit(1)

    withheld = [r for r in rows if not r["claim_eligible"]]
    if withheld:
        print()
        print("Citations are complete and verified, but the following showcases are NOT")
        print("yet eligible for a source-traceability claim on a public surface, because")
        print("the published ruleset does not serve their references:")
        for row in withheld:
            reason = row["claim_blocked_by"] or (
                "the published ruleset declares no citation keys; it needs republishing "
                "on an engine that serves the source-reference contract"
            )
            print(f"  - {row['ruleset_slug']}: {reason}")
    print()
    if args.offline:
        print(
            "OK (structure only)  every participating criterion declares a citation. Nothing was "
            "fetched, digested or quote-checked, and the denominator came from a committed file - "
            "run without --offline before relying on any of it."
        )
    else:
        print("PASS  every participating criterion of every showcase carries a verified citation.")


if __name__ == "__main__":
    main()
