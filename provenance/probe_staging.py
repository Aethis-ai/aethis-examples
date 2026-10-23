#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Probe a live engine and check that what a visitor actually receives is
traceable to its source.

This is the half the repository cannot prove on its own. The manifests say
what each criterion should cite; this asks the deployed engine what it really
serves, on both paths a caller can reach:

    GET  /api/v1/public/rulesets/{ruleset_id}/explain
    POST /api/v1/public/decide      with include_explanation: true in the body

For every showcase it pins the status and the response shape, then for every
criterion the ruleset evaluates it requires at least one source reference and
checks that reference the way a sceptical reader would:

* required contract fields present, with a recognised schema version;
* the target is a safe HTTPS destination (the same validation the publish path
  applies), and its licence is one we are willing to reproduce under;
* the digest is well-formed, and **re-fetching the target reproduces it** - so
  the reference is bound to a version of the document, not merely to its
  address;
* the quoted passage **occurs verbatim in those digested bytes** - a
  paraphrased or drifted quote fails, which is the whole point of quoting;
* the deep link is the one the quote implies;
* the criterion mapping holds - references attach to criteria the ruleset
  actually evaluates;
* and the two paths agree: /explain and /decide serve identical references, so
  a caller cannot be shown one thing and audited on another.

Exits non-zero on any failure and writes a machine-readable report. Every
network call is bounded and nothing prompts, so it is safe in CI.

Usage:
    uv run provenance/probe_staging.py
    uv run provenance/probe_staging.py --base-url "$AETHIS_BASE_URL"
    uv run provenance/probe_staging.py --self-test    # fixture-driven, no network
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "provenance"))

from check_provenance import (  # noqa: E402
    _criteria_of as _criteria_of,
    _http_json as _http_json,
    check_reference as check_reference,
    probe_showcase,
)
from lib.fetching import fetch_source  # noqa: E402
from lib.manifest import ManifestError, load_registry  # noqa: E402
from lib.target_safety import is_production_url  # noqa: E402

ENV_BASE_URL = "AETHIS_BASE_URL"
# Deliberately outside the published tree: `.aethis/` is excluded from the
# public mirror, and this report carries a base URL and raw engine payload
# excerpts that have no business being republished.
DEFAULT_REPORT = ROOT / ".aethis" / "provenance-probe.json"


def _display_path(path: Path) -> str:
    """Repo-relative when it is inside the repo, absolute otherwise.

    ``Path.relative_to`` raises on anything outside the tree, and doing that
    after the file is written turns a successful run into a traceback.
    """
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


# ---------------------------------------------------------------------------
# Self-test: exercise every assertion without a live engine
# ---------------------------------------------------------------------------


def _self_test() -> int:
    """Drive the probe against fixture responses.

    The point is not to test the engine - it is to show that this probe would
    actually catch each failure it claims to catch. A probe nobody has seen go
    red is not evidence of anything.
    """
    from tests.fixtures_probe import run_self_test

    return run_self_test()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--base-url",
        default=os.environ.get(ENV_BASE_URL),
        help="engine to probe; defaults to $AETHIS_BASE_URL, required if unset",
    )
    parser.add_argument("--showcase", action="append", help="limit to named showcase(s)")
    parser.add_argument("--json", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--self-test", action="store_true", help="run the fixture-driven self-test and exit")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="permit probing production; required when verifying an approved production republish",
    )
    args = parser.parse_args()

    if args.self_test:
        sys.path.insert(0, str(ROOT / "provenance"))
        sys.exit(_self_test())

    if not args.base_url:
        parser.error("--base-url or $AETHIS_BASE_URL is required (no default engine is assumed)")

    if is_production_url(args.base_url) and not args.allow_production:
        print(
            "FAIL  refusing to probe production without --allow-production. Verifying an approved "
            "production republish is a deliberate act, not a default. (A guard that prints a warning "
            "and continues is not a guard.)",
            file=sys.stderr,
        )
        sys.exit(2)

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
    if not manifests:
        print("FAIL  no showcases selected; refusing to report PASS having probed nothing", file=sys.stderr)
        sys.exit(2)

    rows = [probe_showcase(m, base_url=args.base_url, fetcher=fetch_source) for m in manifests]
    failures = [f for row in rows for f in row["failures"]]

    report = {
        "artefact": "aethis-examples launch-showcase live provenance probe",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "showcases": rows,
        "failures": failures,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n")

    for row in rows:
        served = row["criteria_with_served_references"]
        total = row["criteria_total"]
        print(
            f"{row['showcase']}: {served if served is not None else 'unknown'}/{total if total is not None else 'unknown'} "
            f"criteria served a source reference (explain {row['explain_status']}, decide {row['decide_status']})"
        )
    print(f"report: {_display_path(args.json)}")

    if failures:
        print(f"\nFAIL  {len(failures)} probe failure(s):", file=sys.stderr)
        for failure in failures[:50]:
            print(f"  [{failure['where']}] {failure['reason_code']}: {failure['message']}", file=sys.stderr)
        if len(failures) > 50:
            print(f"  ... and {len(failures) - 50} more (see the report)", file=sys.stderr)
        sys.exit(1)
    print("\nPASS  every showcased criterion serves a verified, quote-checked source reference.")


if __name__ == "__main__":
    main()
