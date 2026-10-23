#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Verify and preview a launch showcase, refusing unsafe publication.

The engine already fails a publish closed when a declared citation key has no
valid target. That protects against a *broken* citation. It does not protect
against the failure this repository actually shipped for months: a ruleset
whose criteria declare no citation keys at all, which sails through the same
gate vacuously and then serves a visitor an explanation with no source behind
it. This tool closes that hole on the way in.

Before it will send a publish request it requires, for the ruleset about to be
published:

* every criterion in the expected explanation is mapped to at least one
  citation key in the showcase's manifest - a criterion with none is a refusal,
  not a warning;
* every one of those citations passes the full provenance gate: safe HTTPS
  target, allowlisted licence, digest pinned and still matching, and the quoted
  passage occurring verbatim in the fetched document.

It then builds the resolution payload for review. Source verification performs
bounded reads. Publication is disabled because the current API selects the
project latest ruleset without atomically binding it to the graded candidate.
Both --apply and direct publish calls refuse before any write; no credentials
are needed for preview.

Usage:
    uv run provenance/publish_showcase.py --showcase spacecraft-crew-certification
    uv run provenance/publish_showcase.py --showcase spacecraft-crew-certification \
        --project-id proj_... --apply
    uv run provenance/publish_showcase.py --showcase spacecraft-crew-certification \
        --expected-explanation https://api.aethis.ai/api/v1/public/rulesets/.../explain
"""

from __future__ import annotations

import argparse
import json
import http.client
import os
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "provenance"))

from check_provenance import _observed_identity, route_contract_problems, check_showcase  # noqa: E402
from lib.manifest import ManifestError, ShowcaseManifest, load_registry  # noqa: E402
from lib.fetching import read_complete_response  # noqa: E402
from lib.target_safety import TargetSafetyError  # noqa: E402
from lib.json_decode import decode_json  # noqa: E402

APPLY_REFUSAL = (
    "Publication is disabled: the existing publish API selects the project latest "
    "ruleset without atomically binding it to the explanation graded here. "
    "This tool can verify and preview targets only; --apply cannot safely prove "
    "candidate identity. Use a separately reviewed owning publication workflow."
)


class PublishRefused(RuntimeError):
    """The showcase is not fit to publish. Exit non-zero; change nothing."""


def _assert_candidate_matches(
    manifest: ShowcaseManifest, payload: dict, origin: str
) -> None:
    """The candidate must be the ruleset this showcase names.

    Criterion ids alone are not identity: any file with the right ids would
    grade clean, including the explanation of a different ruleset that happens
    to share them. Check the slug the payload reports.
    """
    if not isinstance(payload, dict):
        raise PublishRefused(f"the explanation at {origin} is not an object")
    problems = route_contract_problems(payload, path="explain")
    identity_failures = []
    _observed_identity(payload, selector=payload.get("ruleset_id"), path="explain", failures=identity_failures)
    if problems or identity_failures:
        raise PublishRefused("candidate does not satisfy the actual identified explanation contract")
    slug = payload.get("slug") or payload.get("ruleset_id") or ""
    if not slug:
        raise PublishRefused(
            f"the explanation at {origin} names no slug or ruleset_id, so it cannot be shown to be "
            f"{manifest.ruleset_slug!r}. Refusing to grade a candidate that will not identify itself."
        )
    # Match a real slug exactly. A draft may instead name the complete
    # derived ruleset stem followed by its version boundary, never a prefix.
    if payload.get("slug"):
        matches = payload["slug"] == manifest.ruleset_slug
    else:
        derived_name = "-".join(manifest.ruleset_slug.split("/")[1:])
        stem, separator, version = str(payload.get("ruleset_id", "")).partition(":")
        matches = stem == derived_name and separator == ":" and bool(version)
    if not matches:
        raise PublishRefused(
            f"the explanation at {origin} is for {slug!r}, but this showcase is "
            f"{manifest.ruleset_slug!r}. Refusing to grade one ruleset against another's citations."
        )


def load_expected_explanation(
    manifest: ShowcaseManifest, override: str | None
) -> dict:
    """Identified explanation being graded for target preview.

    Defaults to the committed explanation fixture. Pass a path or an https URL
    to check against a freshly generated ruleset instead - which is what a real
    republish should do, since the fixture describes the ruleset being
    replaced.
    """
    try:
        if override is None:
            payload = decode_json(manifest.explain_fixture.read_text())
            origin = str(manifest.explain_fixture)
        elif override.startswith("https://"):
            request = urllib.request.Request(
                override, headers={"User-Agent": "aethis-examples-publish/1.0"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise PublishRefused("remote candidate requires complete HTTP200")
                payload = decode_json(read_complete_response(response))
            origin = override
        else:
            payload = decode_json(Path(override).read_text())
            origin = override
    except (TargetSafetyError, OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PublishRefused(f"{type(exc).__name__}: candidate observation unavailable") from None
    _assert_candidate_matches(manifest, payload, origin)
    return payload


def build_source_targets(manifest: ShowcaseManifest) -> Dict[str, dict]:
    """The resolution payload: one target per citation key the ruleset cites."""
    targets: Dict[str, dict] = {}
    for key, ref in manifest.references.items():
        doc = manifest.documents[ref.document]
        target = {
            "url": doc.url,
            "title": doc.title,
            "authority": doc.authority,
            "licence": doc.licence,
            "quote": ref.quote.as_wire(),
        }
        if ref.locator:
            target["locator"] = ref.locator
        if doc.source_version:
            target["source_version"] = doc.source_version
        if doc.source_date:
            target["source_date"] = doc.source_date
        if doc.expected_digest:
            target["expected_digest"] = doc.expected_digest
        targets[key] = target
    return targets


def gate(manifest: ShowcaseManifest, expected_criteria: List[dict]) -> dict:
    """Run every refusal condition. Returns the evidence row on success.

    Coverage is measured against **the ruleset about to be published**, not
    against whatever currently sits at that slug. Publishing a candidate and
    grading it on the thing it replaces answers the wrong question - and on a
    target environment holding an older cut it produces pages of drift noise
    that buries the real refusal.
    """
    refusals: List[str] = []
    if route_contract_problems({"criteria": expected_criteria}, path="explain"):
        raise PublishRefused("candidate carries malformed criterion objects or declarations")

    for criterion in expected_criteria:
        criterion_id = criterion.get("criterion_id") or "<unnamed>"
        if not manifest.criteria.get(criterion_id):
            refusals.append(
                f"criterion {criterion_id!r} has no source reference in "
                f"{manifest.manifest_path.relative_to(ROOT)}"
            )

    # The resolution step the engine runs is keyed entirely by the citation keys
    # the ruleset's own criteria declare. A ruleset that declares none short-
    # circuits to an empty result: the publish succeeds, reports success, and
    # resolves nothing. That is the same vacuity this whole gate exists to kill,
    # one layer up, and it is worse because it looks like it worked.
    undeclared = [
        (c.get("criterion_id") or "<unnamed>")
        for c in expected_criteria
        if not (c.get("source_refs") or [])
    ]
    if undeclared:
        refusals.append(
            f"{len(undeclared)}/{len(expected_criteria)} criteria declare no citation keys of their own "
            f"(e.g. {undeclared[:3]}). Supplying source_targets cannot help: resolution is keyed by the "
            "keys the criteria declare, so a publish would resolve nothing and still report success. The "
            "keys have to be authored into the ruleset first - see concessionary-travel-pass for the "
            "shape (source_refs=[...] on each Criterion)."
        )

    row = check_showcase(
        manifest, offline=False, candidate_explain={"criteria": expected_criteria}
    )
    for failure in row["failures"]:
        refusals.append(f"{failure['reason_code']}: {failure['message']}")

    if refusals:
        raise PublishRefused(
            "refusing to publish "
            + manifest.ruleset_slug
            + ":\n  - "
            + "\n  - ".join(refusals)
        )
    return row


def publish(
    manifest: ShowcaseManifest,
    targets: Dict[str, dict],
    *,
    base_url: str,
    project_id: str,
    api_key: str,
    label: str | None,
) -> dict:
    """Refuse writes until the API can bind a request to its graded candidate."""
    raise PublishRefused(APPLY_REFUSAL)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--showcase", required=True, help="showcase name from provenance/showcase.yaml"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AETHIS_BASE_URL", "https://api.aethis.ai"),
    )
    parser.add_argument(
        "--project-id", help="project whose latest ruleset is being published"
    )
    parser.add_argument(
        "--expected-explanation",
        help="path or https URL of the explanation to check against",
    )
    parser.add_argument(
        "--label", help="human-readable label for this published version"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="refused until publication can bind the graded candidate; preview is read-only",
    )
    args = parser.parse_args()
    if args.apply:
        print(f"REFUSED  {APPLY_REFUSAL}", file=sys.stderr)
        sys.exit(1)

    try:
        manifests = load_registry(ROOT)
    except ManifestError as exc:
        print(f"FAIL  manifest error: {exc}", file=sys.stderr)
        sys.exit(2)

    matched = [m for m in manifests if m.name == args.showcase]
    if not matched:
        print(
            f"FAIL  unknown showcase {args.showcase!r}; known: "
            + ", ".join(m.name for m in manifests),
            file=sys.stderr,
        )
        sys.exit(2)
    manifest = matched[0]

    try:
        expected_payload = load_expected_explanation(manifest, args.expected_explanation)
        expected = expected_payload.get("criteria", [])
    except PublishRefused as exc:
        print(f"REFUSED  {exc}", file=sys.stderr)
        sys.exit(1)
    if not expected:
        print(
            "FAIL  the expected explanation lists no criteria; refusing to publish blind",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        row = gate(manifest, expected)
    except PublishRefused as exc:
        print(f"REFUSED  {exc}", file=sys.stderr)
        sys.exit(1)

    targets = build_source_targets(manifest)
    print(
        f"gate passed: {row['criteria_with_verified_citations']}/{row['criteria_total']} criteria "
        f"carry a verified citation; {len(targets)} resolution targets prepared."
    )

    print()
    print("Dry run - nothing was published. Candidate identity and target preview:")
    print(json.dumps({
        "candidate": {key: expected_payload.get(key) for key in (
            "ruleset_id", "slug", "ruleset_version", "content_digest",
        )},
        "slug": manifest.ruleset_slug,
        "source_targets": targets,
        "apply_available": False,
    }, indent=2))


if __name__ == "__main__":
    main()
