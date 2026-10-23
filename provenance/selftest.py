#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Self-tests for the provenance gate: semantics, safety, and non-vacuity.

Three things are checked, and the third is the one that matters most.

1. **Quote-matching semantics** match the engine's, case by case. If this
   repository were stricter than the engine it would block publishes the
   engine would accept; if it were looser it would wave through citations the
   engine then rejects. Either way the gate stops meaning anything.
2. **Target safety** refuses the same destinations the publish path refuses.
3. **Non-vacuity** - the gate is shown going red. Every check below is
   exercised by deliberately breaking the thing it protects: a criterion with
   its citation removed, a citation pointing at nothing, a document left
   unpinned, a licence nobody granted. A gate that has only ever been seen
   green is indistinguishable from a gate that does nothing.

No network, no credentials.

    uv run provenance/selftest.py
"""

from __future__ import annotations

import copy
import json
import dataclasses
import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "provenance"))

from contextlib import contextmanager
from unittest.mock import patch

import yaml  # noqa: E402

from lib import manifest as manifest_lib  # noqa: E402
from lib.manifest import ManifestError, find_restricted_phrase, load_registry  # noqa: E402
from lib.quote_match import (  # noqa: E402
    MEDIA_HTML,
    MEDIA_PDF,
    MEDIA_TEXT,
    PDFExtractionError,
    Quote,
    build_deep_link,
    media_type_from_content_type,
    quote_occurs,
    searchable_text,
)
from lib.target_safety import TargetSafetyError, resolve_and_vet, validate_target_url  # noqa: E402

_results: List[tuple[str, bool, str]] = []



@contextmanager
def deny_network():
    """Fail any unintended HTTP, DNS or socket access during the whole suite."""
    attempted = []
    def denied(*args, **kwargs):
        attempted.append("network access")
        raise AssertionError("offline suite attempted network access")
    with patch("urllib.request.urlopen", denied), patch("socket.getaddrinfo", denied), patch("socket.create_connection", denied), patch("socket.socket.connect", denied):
        yield
    assert not attempted, f"offline suite attempted {len(attempted)} network operation(s)"


def check(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except AssertionError as exc:
        _results.append((name, False, str(exc) or "assertion failed"))
    except Exception as exc:  # noqa: BLE001
        _results.append((name, False, f"{type(exc).__name__}: {exc}"))
    else:
        _results.append((name, True, ""))


def expect_raises(exc_type, fn, *, reason_code: str | None = None) -> None:
    try:
        fn()
    except exc_type as exc:
        if reason_code is not None:
            actual = getattr(exc, "reason_code", None)
            assert actual == reason_code, f"expected reason_code {reason_code!r}, got {actual!r}"
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


# ---------------------------------------------------------------------------
# Quote-matching semantics
# ---------------------------------------------------------------------------

def test_whitespace_is_normalised_on_both_sides() -> None:
    content = b"An applicant\n   must hold\ta valid licence."
    assert quote_occurs(Quote(exact="An applicant must hold a valid licence."), content, MEDIA_TEXT)
    assert quote_occurs(Quote(exact="An applicant\n\nmust hold a valid   licence."), content, MEDIA_TEXT)


def test_html_is_tag_stripped_but_text_is_not() -> None:
    html = b"<p>An applicant <b>must</b> hold a licence.</p>"
    assert quote_occurs(Quote(exact="An applicant must hold a licence."), html, MEDIA_HTML)
    # The same bytes treated as plain text still contain the markup, so the
    # prose-only quote must NOT match: media type changes the answer.
    assert not quote_occurs(Quote(exact="An applicant must hold a licence."), html, MEDIA_TEXT)


def test_script_and_style_content_is_removed_for_html() -> None:
    html = b"<style>p{color:red}</style><script>var x='hidden text';</script><p>Real prose.</p>"
    assert quote_occurs(Quote(exact="Real prose."), html, MEDIA_HTML)
    assert not quote_occurs(Quote(exact="hidden text"), html, MEDIA_HTML)


def test_matching_is_case_sensitive_and_order_sensitive() -> None:
    content = b"An applicant must hold a valid licence."
    assert not quote_occurs(Quote(exact="an applicant must hold a valid licence."), content, MEDIA_TEXT)
    assert not quote_occurs(Quote(exact="must hold An applicant a valid licence."), content, MEDIA_TEXT)


def test_paraphrase_does_not_match() -> None:
    content = b"An applicant must hold a valid licence."
    assert not quote_occurs(Quote(exact="Applicants need a licence."), content, MEDIA_TEXT)


def test_empty_quote_never_matches() -> None:
    assert not quote_occurs(Quote(exact=""), b"anything at all", MEDIA_TEXT)
    assert not quote_occurs(Quote(exact="   \n  "), b"anything at all", MEDIA_TEXT)


def test_undecodable_bytes_do_not_crash_the_check() -> None:
    content = "An applicant must hold a licence.".encode() + b"\xff\xfe\x00"
    assert quote_occurs(Quote(exact="An applicant must hold a licence."), content, MEDIA_TEXT)


def test_media_type_mapping() -> None:
    assert media_type_from_content_type("text/html; charset=utf-8") == MEDIA_HTML
    assert media_type_from_content_type("application/xhtml+xml") == MEDIA_HTML
    assert media_type_from_content_type("application/pdf") == MEDIA_PDF
    assert media_type_from_content_type("text/plain; charset=utf-8") == MEDIA_TEXT
    assert media_type_from_content_type("") == MEDIA_TEXT


def test_searchable_text_strips_only_for_html() -> None:
    raw = b"<p>hello</p>"
    assert searchable_text(raw, MEDIA_HTML) == "hello"
    assert searchable_text(raw, MEDIA_TEXT) == "<p>hello</p>"


def test_unparseable_pdf_fails_closed() -> None:
    assert not quote_occurs(Quote(exact="anything"), b"not a pdf at all", MEDIA_PDF)


def test_missing_pdf_extractor_raises_rather_than_passing() -> None:
    import lib.quote_match as qm

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def blocked(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("pypdf is not installed")
        return real_import(name, *args, **kwargs)

    if isinstance(__builtins__, dict):
        __builtins__["__import__"] = blocked
    else:
        __builtins__.__import__ = blocked
    try:
        expect_raises(PDFExtractionError, lambda: qm.extract_pdf_page_texts(b"%PDF-1.4"))
    finally:
        if isinstance(__builtins__, dict):
            __builtins__["__import__"] = real_import
        else:
            __builtins__.__import__ = real_import


def test_deep_link_forms() -> None:
    quote = Quote(exact="a valid licence", prefix="must hold", suffix="at all times")
    link = build_deep_link("https://example.test/act", quote, MEDIA_TEXT)
    assert link == "https://example.test/act#:~:text=must%20hold-,a%20valid%20licence,-at%20all%20times", link

    plain = build_deep_link("https://example.test/act#old", Quote(exact="a b"), MEDIA_TEXT)
    assert plain == "https://example.test/act#:~:text=a%20b", plain

    pdf = build_deep_link("https://example.test/act.pdf", Quote(exact="x"), MEDIA_PDF, "page 12")
    assert pdf == "https://example.test/act.pdf#page=12", pdf

    found = build_deep_link("https://example.test/act.pdf", Quote(exact="x"), MEDIA_PDF, "page 12", pdf_page=3)
    assert found == "https://example.test/act.pdf#page=3", found


def test_deep_link_percent_encodes_markup_in_the_quote() -> None:
    link = build_deep_link("https://example.test/a", Quote(exact='"><script>alert(1)</script>'), MEDIA_TEXT)
    assert "<" not in link and ">" not in link and '"' not in link, link


# ---------------------------------------------------------------------------
# Target safety
# ---------------------------------------------------------------------------

def test_non_https_schemes_are_refused() -> None:
    for url in ("http://example.test/a", "ftp://example.test/a", "file:///etc/passwd", "javascript:alert(1)"):
        expect_raises(TargetSafetyError, lambda u=url: validate_target_url(u), reason_code="unsafe_scheme")


def test_credentials_in_url_are_refused() -> None:
    expect_raises(
        TargetSafetyError,
        lambda: validate_target_url("https://user:pass@example.test/a"),
        reason_code="credentials_in_url",
    )


def test_ip_literal_hosts_are_refused_including_encodings() -> None:
    for host in ("127.0.0.1", "2130706433", "0x7f000001", "[::1]"):
        expect_raises(
            TargetSafetyError,
            lambda h=host: validate_target_url(f"https://{h}/a"),
            reason_code="ip_literal_host",
        )


def test_non_default_port_is_refused() -> None:
    expect_raises(
        TargetSafetyError, lambda: validate_target_url("https://example.test:8443/a"), reason_code="unsafe_port"
    )


def test_private_destinations_are_refused_after_dns() -> None:
    for addr in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "::ffff:192.168.0.1"):
        expect_raises(
            TargetSafetyError,
            lambda a=addr: resolve_and_vet("example.test", lambda _host: [a]),
            reason_code="private_destination",
        )


def test_public_destination_is_accepted() -> None:
    assert resolve_and_vet("example.test", lambda _host: ["93.184.216.34"]) == "93.184.216.34"


def test_mixed_resolution_is_refused_if_any_address_is_private() -> None:
    expect_raises(
        TargetSafetyError,
        lambda: resolve_and_vet("example.test", lambda _host: ["93.184.216.34", "127.0.0.1"]),
        reason_code="private_destination",
    )


def test_url_normalisation_drops_the_fragment() -> None:
    normalised, host = validate_target_url("https://Example.TEST/a/b?x=1#frag")
    assert normalised == "https://example.test/a/b?x=1", normalised
    assert host == "example.test"


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------

def _write_manifest(tmp: Path, mutate) -> Path:
    base = {
        "schema_version": 1,
        "documents": {
            "act": {
                "url": "https://example.test/act.md",
                "title": "Act",
                "authority": "Authority",
                "licence": "MIT",
                "media_type": "text",
                "expected_digest": "sha256:" + "a" * 64,
            }
        },
        "references": {
            "ACT#S1": {"document": "act", "locator": "s1", "quote": {"exact": "some passage"}},
        },
        "criteria": {"c1": ["ACT#S1"]},
    }
    mutate(base)
    path = tmp / "references.yaml"
    path.write_text(yaml.safe_dump(base))
    fixture = tmp / "f.explain.json"
    fixture.write_text('{"criteria": [{"criterion_id": "c1", "source_refs": []}]}')
    return path


def _load(tmp: Path, mutate):
    _write_manifest(tmp, mutate)
    entry = {
        "name": "t",
        "example_dir": ".",
        "ruleset_slug": "aethis/t",
        "references": "references.yaml",
        "explain_fixture": "f.explain.json",
    }
    return manifest_lib.load_showcase_manifest(tmp, entry)


def test_unallowlisted_licence_is_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        expect_raises(
            ManifestError,
            lambda: _load(tmp, lambda m: m["documents"]["act"].update(licence="All rights reserved")),
        )


def test_missing_licence_is_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        expect_raises(ManifestError, lambda: _load(tmp, lambda m: m["documents"]["act"].pop("licence")))


def test_dangling_document_reference_is_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        expect_raises(
            ManifestError, lambda: _load(tmp, lambda m: m["references"]["ACT#S1"].update(document="nope"))
        )


def test_dangling_citation_key_is_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        expect_raises(ManifestError, lambda: _load(tmp, lambda m: m["criteria"].update(c1=["ACT#MISSING"])))


def test_criterion_with_no_citation_keys_is_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        expect_raises(ManifestError, lambda: _load(tmp, lambda m: m["criteria"].update(c1=[])))


def test_malformed_digest_is_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        expect_raises(
            ManifestError, lambda: _load(tmp, lambda m: m["documents"]["act"].update(expected_digest="abc"))
        )


def test_forbidden_content_is_refused() -> None:
    """A quote inside the restricted boundary must fail the manifest load.

    The probe phrase is injected for the duration of the test rather than taken
    from the real boundary, so proving the mechanism works does not require
    writing a restricted phrase into a file that ships publicly.
    """
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        expect_raises(
            ManifestError,
            lambda: _load(
                tmp,
                lambda m: m["references"]["ACT#S1"]["quote"].update(
                    exact=f"a clause concerning {_a_restricted_phrase()} in the schedule"
                ),
            ),
        )
    with tempfile.TemporaryDirectory() as d:
        _load(Path(d), lambda m: None)


def test_wrong_schema_version_is_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        expect_raises(ManifestError, lambda: _load(tmp, lambda m: m.update(schema_version=99)))


# ---------------------------------------------------------------------------
# Gate non-vacuity: break the real manifests, watch the gate go red
# ---------------------------------------------------------------------------

def _real_manifests():
    return load_registry(ROOT)


def _offline_fixture_documents(
    manifests: list[manifest_lib.ShowcaseManifest], payloads: dict[str, dict[str, Any]]
) -> dict[str, manifest_lib.SourceDocument]:
    """Map retained fixture URLs to local corpus bytes without hiding drift."""
    documents = {document.url: document for manifest in manifests for document in manifest.documents.values()}
    for manifest in manifests:
        by_digest = {document.expected_digest: document for document in manifest.documents.values()}
        # Retained earlier versions of a cited document (``<example>/retained``,
        # a sibling of the ``sources/`` directory so authoring never uploads
        # them) resolve by digest, so a fixture recorded against an older text is
        # replayed against exactly those bytes rather than the current ones.
        for document in list(manifest.documents.values()):
            if not document.local_path:
                continue
            for retained in sorted((ROOT / document.local_path).parent.parent.glob("retained/*.sha256-*.md")):
                digest = "sha256:" + hashlib.sha256(retained.read_bytes()).hexdigest()
                by_digest.setdefault(
                    digest,
                    dataclasses.replace(
                        document, expected_digest=digest, local_path=str(retained.relative_to(ROOT))
                    ),
                )
        by_quote = {
            reference.quote.exact: manifest.documents[reference.document]
            for reference in manifest.references.values()
        }
        for criterion in payloads[manifest.ruleset_slug]["criteria"]:
            for fixture_reference in criterion["source_references"]:
                quote = fixture_reference.get("quote")
                document = by_digest.get(fixture_reference.get("content_digest")) or by_quote.get(
                    quote.get("exact") if isinstance(quote, dict) else None
                )
                if document:
                    documents.setdefault(fixture_reference["url"], document)
    return documents


def _codes(row: dict) -> set:
    return {f["reason_code"] for f in row["failures"]}


def test_real_manifests_are_structurally_clean() -> None:
    from check_provenance import check_showcase

    for showcase in _real_manifests():
        live = {"criteria": [{"criterion_id": c, "source_refs": []} for c in showcase.fixture_criteria()]}
        row = check_showcase(showcase, offline=True, live_explain=live)
        assert not row["failures"], f"{showcase.name}: {row['failures']}"
        assert row["criteria_declaring_citations"] == row["criteria_total"], (
            f"{showcase.name} declares {row['criteria_declaring_citations']}/{row['criteria_total']}"
        )


def test_removing_one_criterion_citation_turns_the_gate_red() -> None:
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    victim = showcase.fixture_criteria()[0]
    broken = copy.copy(showcase)
    broken.criteria = {k: v for k, v in showcase.criteria.items() if k != victim}
    live = {"criteria": [{"criterion_id": c, "source_refs": []} for c in showcase.fixture_criteria()]}
    row = check_showcase(broken, offline=True, live_explain=live)
    assert "uncited_criterion" in _codes(row), f"expected uncited_criterion, got {_codes(row)}"
    assert row["criteria_declaring_citations"] < row["criteria_total"], "declared count must fall"


def test_citing_a_criterion_the_ruleset_no_longer_evaluates_turns_the_gate_red() -> None:
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    broken = copy.copy(showcase)
    broken.criteria = dict(showcase.criteria)
    broken.criteria["a_criterion_that_does_not_exist"] = list(showcase.references)[:1]
    row = check_showcase(broken, offline=True)
    assert "stale_criterion" in _codes(row), f"expected stale_criterion, got {_codes(row)}"


def test_unpinned_document_turns_the_gate_red() -> None:
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    doc_id, doc = next(iter(showcase.documents.items()))
    broken = copy.copy(showcase)
    broken.documents = dict(showcase.documents)
    broken.documents[doc_id] = manifest_lib.SourceDocument(
        doc_id=doc.doc_id,
        url=doc.url,
        title=doc.title,
        authority=doc.authority,
        licence=doc.licence,
        media_type=doc.media_type,
        expected_digest=None,
    )
    row = check_showcase(broken, offline=True)
    assert "unpinned_document" in _codes(row), f"expected unpinned_document, got {_codes(row)}"


def test_every_showcase_covers_every_criterion_the_engine_evaluates() -> None:
    for showcase in _real_manifests():
        participating = showcase.fixture_criteria()
        assert participating, f"{showcase.name} has an empty denominator"
        uncited = [c for c in participating if not showcase.criteria.get(c)]
        assert not uncited, f"{showcase.name} leaves {uncited} uncited"


# ---------------------------------------------------------------------------
# The guarantees an independent review found missing. Each is asserted by
# breaking it, because every one of these was green while untrue.
# ---------------------------------------------------------------------------

def test_denominator_comes_from_the_live_response_not_the_fixture() -> None:
    """The engine's criterion list wins over the committed fixture.

    This is the test that stands between the blocker-1 fix and a silent
    regression, so it has to be written so that only the fix can pass it. The
    first version built its `live` payload *from* `fixture_criteria()`, which
    made the two lists identical - it could not tell the implementations apart,
    and a reviewer flipped `participating = live_criteria` back to the fixture
    with the suite still green.

    The construction here is deliberate: `live` carries a criterion the fixture
    does **not** have, and the manifest does not cite it. Reading the fixture
    yields a clean N; reading the engine yields N+1 with one uncited. Only the
    correct implementation can produce the second.
    """
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    fixture = showcase.fixture_criteria()
    ghost = "a_criterion_only_the_engine_knows_about"
    assert ghost not in fixture and ghost not in showcase.criteria

    live = {"criteria": [{"criterion_id": c, "source_refs": []} for c in fixture + [ghost]]}
    row = check_showcase(showcase, offline=True, live_explain=live)
    codes = _codes(row)

    # Reading the fixture would give len(fixture); the engine says one more.
    assert row["criteria_total"] == len(fixture) + 1, (
        f"denominator is {row['criteria_total']}, expected {len(fixture) + 1} from the live payload - "
        "the fixture is being used as the denominator"
    )
    # And the extra criterion has to be reported as uncited, not ignored.
    assert "uncited_criterion" in codes, f"expected uncited_criterion for {ghost!r}, got {codes}"
    assert any(f.get("criterion") == ghost for f in row["failures"]), (
        f"the live-only criterion {ghost!r} was not the one reported"
    )
    # The drift between engine and fixture must also surface.
    assert "fixture_drift" in codes, f"expected fixture_drift, got {codes}"


def test_removing_a_criterion_from_the_fixture_cannot_shrink_the_total() -> None:
    """The reviewer's original attack, as a permanent test.

    Deleting a criterion from the committed fixture and its citation mapping
    took the suite to a green 9/9 for a ten-criterion ruleset. Here the fixture
    is short and the engine is complete, which is exactly that shape.
    """
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    fixture = showcase.fixture_criteria()
    victim = fixture[-1]

    trimmed = copy.copy(showcase)
    trimmed.criteria = {k: v for k, v in showcase.criteria.items() if k != victim}
    live = {"criteria": [{"criterion_id": c, "source_refs": []} for c in fixture]}

    row = check_showcase(trimmed, offline=True, live_explain=live)
    assert row["criteria_total"] == len(fixture), "the total must not follow the manifest"
    assert "uncited_criterion" in _codes(row)
    assert row["manifest_coverage"] != 1.0 if row["manifest_coverage"] is not None else True


def test_fixture_disagreeing_with_the_engine_is_reported() -> None:
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    fixture = showcase.fixture_criteria()
    live = {"criteria": [{"criterion_id": c, "source_refs": []} for c in fixture[:-1]]}
    row = check_showcase(showcase, offline=True, live_explain=live)
    assert "fixture_drift" in _codes(row), f"expected fixture_drift, got {_codes(row)}"


def test_offline_reports_no_verified_count() -> None:
    """An offline run must not produce a number a consumer reads as verified.

    The committed artefact was generated offline and still said 30 criteria
    carried verified citations, when nothing had been fetched. The count now
    does not exist unless the verification ran.
    """
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    row = check_showcase(showcase, offline=True)
    assert row["criteria_with_verified_citations"] is None
    assert row["manifest_coverage"] is None
    assert row["criteria_declaring_citations"] == row["criteria_total"]


def test_served_coverage_is_unverified_without_a_live_response() -> None:
    """The review's blocker 2: a forged fixture must not be able to authorise a
    public claim. With no live answer there is no honest served number, so it is
    reported as unknown and the showcase cannot be eligible."""
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    row = check_showcase(showcase, offline=True, live_explain=None)
    assert row["served_coverage"] is None, "served coverage must be unknown, not a number"
    assert row["criteria_served_by_engine"] is None
    assert row["claim_eligible"] is False, "an unverified showcase must never be claim-eligible"
    assert row["denominator_source"] == "fixture (unverified)"


def test_forged_fixture_references_cannot_make_a_showcase_eligible() -> None:
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    fixture = showcase.fixture_criteria()
    # The fixture claims every criterion serves a reference; the engine says none do.
    live = {"criteria": [{"criterion_id": c, "source_refs": []} for c in fixture]}
    row = check_showcase(showcase, offline=True, live_explain=live)
    assert row["criteria_served_by_engine"] is None, "offline served coverage must remain unknown"
    assert row["claim_eligible"] is False


def test_manifest_keys_must_match_the_keys_the_ruleset_declares() -> None:
    from check_provenance import check_showcase

    showcase = _real_manifests()[0]
    fixture = showcase.fixture_criteria()
    live = {
        "criteria": [
            {"criterion_id": c, "source_refs": ["a-key-the-manifest-does-not-have"]} for c in fixture
        ]
    }
    row = check_showcase(showcase, offline=True, live_explain=live)
    assert "citation_key_mismatch" in _codes(row), f"expected citation_key_mismatch, got {_codes(row)}"


def test_locally_edited_corpus_turns_the_gate_red() -> None:
    """A self-cited document must match the bytes actually being cited."""
    from check_provenance import _check_local_copies

    showcase = next(m for m in _real_manifests() if any(d.local_path for d in m.documents.values()))
    doc = next(d for d in showcase.documents.values() if d.local_path)
    broken = copy.copy(showcase)
    broken.documents = dict(showcase.documents)
    broken.documents[doc.doc_id] = manifest_lib.SourceDocument(
        doc_id=doc.doc_id,
        url=doc.url,
        title=doc.title,
        authority=doc.authority,
        licence=doc.licence,
        media_type=doc.media_type,
        expected_digest="sha256:" + "b" * 64,
        local_path=doc.local_path,
    )
    failures: list = []
    _check_local_copies(broken, failures)
    codes = {f["reason_code"] for f in failures}
    assert "local_copy_diverged" in codes, f"expected local_copy_diverged, got {codes}"


def test_every_self_cited_document_declares_a_local_path() -> None:
    """Otherwise the previous check silently does nothing for it."""
    for showcase in _real_manifests():
        for doc in showcase.documents.values():
            if "raw.githubusercontent.com/Aethis-ai/aethis-examples/" in doc.url:
                assert doc.local_path, (
                    f"{showcase.name}/{doc.doc_id} cites this repository's own published copy but "
                    "declares no local_path, so a local edit could never be detected"
                )


def test_registry_cannot_lose_a_showcase_silently() -> None:
    """Deleting an entry shrinks the total that everything else is measured
    against, so the lock file has to notice."""
    lock = ROOT / "provenance" / "showcase.lock"
    assert lock.is_file(), "provenance/showcase.lock is missing; the registry has no independent record"
    locked = [
        line.strip() for line in lock.read_text().splitlines() if line.strip() and not line.startswith("#")
    ]
    assert locked, "the lock file records no showcases"
    present = {m.ruleset_slug for m in _real_manifests()}
    assert not [s for s in locked if s not in present]

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "showcase.lock").write_text("aethis/a-showcase-that-was-deleted\n")
        (tmp / "showcase.yaml").write_text(
            "schema_version: 1\nshowcases:\n  - name: t\n    example_dir: .\n"
            "    ruleset_slug: aethis/t\n    references: references.yaml\n"
            "    explain_fixture: f.explain.json\n"
        )
        _write_manifest(tmp, lambda m: None)
        expect_raises(ManifestError, lambda: manifest_lib.load_registry(tmp, tmp / "showcase.yaml"))


def _a_restricted_phrase() -> str:
    """One phrase from the internal boundary list.

    Taken at runtime rather than written here: this file ships to the public
    mirror, and a test that hard-codes a restricted phrase to prove restricted
    phrases are caught would publish the very thing the list is kept back to
    avoid.
    """
    return manifest_lib.load_restricted_phrases()[0]


def test_restricted_boundary_is_plaintext_named_and_inflection_covering() -> None:
    """The boundary names what it caught, and a stem covers its inflections.

    An earlier version hashed the phrases. That was obscurity, not security -
    a reviewer recovered nine of ten digests from a short word list in
    milliseconds - and it cost two real things: inflections stopped matching,
    and the error could no longer say which words tripped it. Exclusion from
    the published mirror is what protects the list; plaintext is what makes it
    usable.
    """
    probe = ("widget smuggling",)
    assert find_restricted_phrase("a schedule concerning Widget Smuggling here", probe) == "widget smuggling"
    assert find_restricted_phrase("an entirely ordinary passage", probe) is None

    real = manifest_lib.load_restricted_phrases()
    assert len(real) >= 5, "the boundary is empty or nearly so; it would be decorative"

    # Inflection coverage, without writing an inflection into this file: build
    # derived forms from whatever stems the internal list actually holds.
    stem = min(real, key=len)
    for suffix in ("", "ation", "ations", "ed", "s"):
        candidate = f"a {stem}{suffix} appears in the register"
        assert find_restricted_phrase(candidate, real) == stem, f"{stem}{suffix!r} slipped through"
    # Case-insensitive.
    assert find_restricted_phrase(f"A {stem.upper()} REFERENCE", real) == stem
    # And it names the phrase, so an author gets an actionable message rather
    # than being told "no" and left to guess.
    longest = max(real, key=len)
    assert find_restricted_phrase(f"see the {longest} for detail", real) == longest


def test_missing_boundary_list_fails_closed() -> None:
    """A check that cannot run must not report success."""
    with tempfile.TemporaryDirectory() as d:
        expect_raises(
            manifest_lib.RestrictedBoundaryUnavailable,
            lambda: manifest_lib.load_restricted_phrases(Path(d) / "not-here.txt"),
        )


def test_corpus_files_are_scanned_not_just_quoted_passages() -> None:
    """The scanner must read whole corpus files.

    Scanning only the quoted passages meant a restricted phrase anywhere else
    in a source document was invisible - and one was, in a modelling note on
    the published mirror. This asserts the sweep reaches file content the
    manifests never quote.
    """
    findings = manifest_lib.scan_corpus_documents(_real_manifests(), ROOT)
    assert isinstance(findings, list)
    for finding in findings:
        assert {"showcase", "document", "path", "line", "phrase"} <= set(finding)
    # The sweep must actually be looking at files, not returning [] because it
    # never opened one.
    scanned = {
        d.local_path
        for m in _real_manifests()
        for d in m.documents.values()
        if d.local_path
    }
    assert scanned, "no showcase declares a local_path, so the corpus sweep covers nothing"


def test_a_tampered_evidence_artefact_is_rejected() -> None:
    """Editing the artefact must not survive verification.

    A reviewer hand-set `claim_eligible: true` on all four showcases and it
    passed the whole suite, the live gate and CI. Enumerating fields to protect
    is a losing game, so verification recomputes the artefact and diffs it.
    This drives that comparison offline: a stored artefact whose numbers do not
    match a fresh run must be rejected, whatever was changed.
    """
    import check_provenance as cp

    manifests = _real_manifests()
    fresh = cp.build_evidence(manifests, offline=True, base_url="https://unused.test")
    payloads = {m.ruleset_slug: json.loads(m.explain_fixture.read_text()) for m in manifests}
    docs = _offline_fixture_documents(manifests, payloads)
    def transport(url, *, method="GET", body=None):
        from urllib.parse import unquote
        slug = body["ruleset_id"] if method == "POST" else unquote(url.split("/rulesets/")[1].removesuffix("/explain"))
        payload = payloads[slug]
        return (200, __import__("tests.fixtures_probe", fromlist=["_decide_payload"])._decide_payload(payload)) if method == "POST" else (200, payload)
    def fetch(url):
        from lib.fetching import FetchedSource
        doc = docs[url]
        if not doc.local_path:
            raise TargetSafetyError("offline_source_unavailable", "no local offline corpus bytes")
        return FetchedSource(url=url, content=(ROOT / doc.local_path).read_bytes(), media_type=doc.media_type)
    for mutate in (
        lambda a: [r.update(claim_eligible=True) for r in a["showcases"]],
        lambda a: a["totals"].update(criteria_total=999),
        lambda a: a["binding"]["fixture_digests"].clear(),
    ):
        forged = copy.deepcopy(fresh)
        mutate(forged)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "coverage.json"
            path.write_text(json.dumps(forged, indent=2))
            rc = cp.verify_artefact(manifests, path, "https://unused.test", transport=transport, source_fetcher=fetch)
            assert rc == 1, f"a forged artefact verified clean: {mutate}"

    # And an honest offline artefact is still rejected for being offline.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "coverage.json"
        path.write_text(json.dumps(fresh, indent=2))
        assert cp.verify_artefact(manifests, path, "https://unused.test", transport=transport, source_fetcher=fetch) == 1


def test_volatile_fields_are_excluded_but_nothing_else_is() -> None:
    """The freshness check must be satisfiable by an honest run, and only by one.

    Two honest runs of the same tree differ in `generated_at` (wall clock) and
    `binding.commit` (the checkout commit - in a pull-request build an
    ephemeral merge commit that can never equal the branch head the artefact
    was committed on). A byte comparison of the whole artefact is therefore
    unsatisfiable by construction: it fails on every PR forever. That is the
    mirror image of a test that can only pass - a gate that can only fail gets
    switched off, and the guarantee behind it quietly stops being enforced.

    So those two fields are excluded, and this pins exactly which: anything
    else drifting into the exclusion set would silently stop being protected.
    """
    import check_provenance as cp

    manifests = _real_manifests()
    fresh = cp.build_evidence(manifests, offline=True, base_url="https://unused.test")

    view = cp.substantive(fresh)
    assert "generated_at" not in view
    assert "commit" not in view["binding"]
    # Everything a consumer relies on survives into the compared view.
    for key in ("mode", "totals", "showcases", "corpus_findings", "failures", "binding"):
        assert key in view, f"{key} must still be compared"
    for key in ("fixture_digests", "manifest_digests"):
        assert key in view["binding"], f"binding.{key} must still be compared"

    # Differing only in the volatile fields verifies clean...
    drifted = copy.deepcopy(fresh)
    drifted["generated_at"] = "1999-01-01T00:00:00+00:00"
    drifted["binding"]["commit"] = "0" * 40
    assert cp.substantive(drifted) == cp.substantive(fresh)

    # ...while any substantive change does not.
    for mutate in (
        lambda a: a["totals"].update(criteria_with_verified_citations=99),
        lambda a: a["showcases"][0].update(claim_eligible=True),
        lambda a: a.update(mode="verified" if a["mode"] != "verified" else "degraded"),
        lambda a: a["binding"]["fixture_digests"].update({"x": "sha256:" + "0" * 64}),
    ):
        forged = copy.deepcopy(fresh)
        mutate(forged)
        assert cp.substantive(forged) != cp.substantive(fresh), f"{mutate} was not detected"


# ---------------------------------------------------------------------------
# Served references must agree with verified targets, not just opaque keys.
# The positive input is an existing recorded publication, never reconstructed
# from the checker output. Source reads use its actual committed corpus bytes.
# ---------------------------------------------------------------------------

def _recorded_served_check(
    mutate: Callable[[dict], None] | None = None, *, offline: bool = False, drift: bool = False,
    legacy: bool = False, all_unserved: bool = False,
) -> dict:
    from unittest.mock import patch

    import check_provenance as cp
    from lib.fetching import FetchedSource

    showcase = next(m for m in _real_manifests() if m.name == "consumer-credit-prequalification")
    payload = json.loads(showcase.explain_fixture.read_text())
    if legacy:
        for criterion in payload["criteria"]:
            for reference in criterion["source_references"]:
                reference.pop("snapshot", None)
    if all_unserved:
        for criterion in payload["criteria"]:
            criterion["source_refs"] = []
            criterion["source_references"] = []
    if mutate:
        mutate(payload["criteria"][0])
    by_url = {doc.url: doc for doc in showcase.documents.values()}

    def fetch(url: str) -> FetchedSource:
        doc = by_url[url]
        content = (ROOT / doc.local_path).read_bytes()
        if drift:
            content += b"\nchanged source bytes\n"
        return FetchedSource(url=url, content=content, media_type=doc.media_type)

    with patch.object(cp, "fetch_source", fetch):
        return cp.check_showcase(showcase, offline=offline, live_explain=payload)


def test_live_http_status_is_complete(status: int) -> None:
    import check_provenance as cp
    from unittest.mock import patch
    class Response:
        headers = {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def getcode(self):
            return status
        def read(self, amt=None):
            return b'{"criteria": []}'
    with patch.object(cp.urllib.request, "urlopen", return_value=Response()):
        if status == 200:
            assert cp.fetch_live_explain("aethis/example", "https://example.test") == {"criteria": []}
        else:
            try:
                cp.fetch_live_explain("aethis/example", "https://example.test")
            except ValueError:
                pass
            else:
                raise AssertionError(f"HTTP {status} became a complete live observation")


def test_recorded_served_references_are_a_genuine_positive_control() -> None:
    row = _recorded_served_check()
    assert not row["failures"], row["failures"]
    assert row["criteria_served_by_engine"] == row["criteria_total"]
    assert row["served_coverage"] == 1.0 and row["served_path_eligible"] is True
    assert row["claim_eligible"] is False


def test_legacy_v1_references_without_snapshot_are_valid() -> None:
    row = _recorded_served_check(legacy=True)
    assert not row["failures"] and row["served_path_eligible"] is True and row["claim_eligible"] is False, row
    assert row["served_coverage"] == 1.0


def test_v1_url_referent_markers_are_legitimate_positive_controls() -> None:
    for marker in (None, "url"):
        row = _recorded_served_check(lambda c, m=marker: c["source_references"][0].update(
            target_kind=m, artefact_project_id=None, artefact_source_id=None,
        ), legacy=True)
        assert not row["failures"] and row["served_path_eligible"] is True and row["claim_eligible"] is False, row
        assert row["served_coverage"] == 1.0


def test_online_all_unserved_criteria_fail_closed() -> None:
    row = _recorded_served_check(all_unserved=True)
    assert row["criteria_served_by_engine"] == 0 and row["served_coverage"] == 0.0, row
    assert row["claim_eligible"] is False
    assert "served_reference_set_mismatch" in _codes(row)


def test_publisher_rejects_prefix_identity_and_preserves_candidate() -> None:
    from publish_showcase import PublishRefused, _assert_candidate_matches, load_expected_explanation
    showcase = next(m for m in _real_manifests() if m.name == "spacecraft-crew-certification")
    payload = json.loads(showcase.explain_fixture.read_text())
    for changed in (
        {**payload, "slug": showcase.ruleset_slug + "-evil"},
        {**payload, "slug": None, "ruleset_id": "spacecraft-crew-certification-evil:20260101-abcd"},
    ):
        expect_raises(PublishRefused, lambda c=changed: _assert_candidate_matches(showcase, c, "test"))
    loaded = load_expected_explanation(showcase, None)
    assert loaded["ruleset_id"] == payload["ruleset_id"]
    assert loaded["content_digest"] == payload["content_digest"]


def test_publisher_apply_refuses_before_any_network_or_credential() -> None:
    from unittest.mock import patch

    import publish_showcase as publisher
    showcase = next(m for m in _real_manifests() if m.name == "spacecraft-crew-certification")
    with patch.object(publisher.urllib.request, "urlopen", side_effect=AssertionError("unexpected network")):
        expect_raises(publisher.PublishRefused, lambda: publisher.publish(
            showcase, {}, base_url="https://staging.example.test", project_id="unverified-project",
            api_key="unused", label=None,
        ))
        with patch.object(sys, "argv", ["publish_showcase.py", "--showcase", showcase.name, "--apply"]):
            try:
                publisher.main()
            except SystemExit as exc:
                assert exc.code == 1
            else:
                raise AssertionError("--apply did not refuse")


def test_served_reference_mutation(mutate: Callable[[dict], None]) -> None:
    row = _recorded_served_check(mutate)
    assert row["claim_eligible"] is False, "altered served reference still authorises the claim"
    assert row["criteria_served_by_engine"] == row["criteria_total"] - 1, row
    assert row["served_coverage"] < 1.0
    assert _codes(row) & {"served_reference_mismatch", "served_reference_set_mismatch"}, row["failures"]


def test_served_quote_whitespace_uses_existing_matching_semantics() -> None:
    def mutate(c: dict) -> None:
        c["source_references"][0]["quote"]["exact"] = "  \n" + c["source_references"][0]["quote"]["exact"].replace(" ", "\n  ")
    row = _recorded_served_check(mutate)
    assert not row["failures"] and row["served_path_eligible"] is True and row["claim_eligible"] is False, row


def test_source_drift_still_fails_before_served_certification() -> None:
    row = _recorded_served_check(drift=True)
    assert "digest_mismatch" in _codes(row), row["failures"]
    assert row["claim_eligible"] is False
    assert row["criteria_served_by_engine"] == 0


def test_offline_recorded_references_do_not_supply_verified_coverage() -> None:
    row = _recorded_served_check(offline=True)
    assert row["served_coverage"] is None and row["criteria_served_by_engine"] is None
    assert row["manifest_coverage"] is None and row["claim_eligible"] is False


def test_candidate_publish_preflight_never_claims_served_evidence() -> None:
    from unittest.mock import patch

    import check_provenance as cp
    from lib.fetching import FetchedSource
    from publish_showcase import gate

    showcase = next(m for m in _real_manifests() if m.name == "consumer-credit-prequalification")
    criteria = json.loads(showcase.explain_fixture.read_text())["criteria"]
    for criterion in criteria:
        criterion.pop("source_references")
    docs = {doc.url: doc for doc in showcase.documents.values()}
    def fetch(url: str) -> FetchedSource:
        doc = docs[url]
        return FetchedSource(url=url, content=(ROOT / doc.local_path).read_bytes(), media_type=doc.media_type)
    with patch.object(cp, "fetch_source", fetch):
        row = gate(showcase, criteria)
    assert not row["failures"] and row["manifest_coverage"] == 1.0, row
    assert row["denominator_source"] == "candidate"
    assert row["served_coverage"] is None and row["claim_eligible"] is False



def test_main_consumer_observes_both_paths(case: str) -> None:
    import check_provenance as cp
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _decide_criteria, _fetcher, _transport_for

    explain, decide = _payload(), _decide_payload()
    kwargs = {}
    if case == "null decision":
        decide["explanation"] = None
    elif case == "failed decision":
        kwargs["decide_status"] = 500
    elif case == "partial decision":
        kwargs["decide_status"] = 206
    elif case == "divergent decision":
        _decide_criteria(decide)[0]["source_references"][0]["authority"] = "Fabricated"
    elif case == "null explain criterion":
        explain["criteria"][0] = None
    elif case == "null decision criterion":
        decide["explanation"]["groups"][0]["criteria"][0] = None
    elif case == "null reference":
        explain["criteria"][0]["source_references"] = [None]
    elif case == "null quote":
        explain["criteria"][0]["source_references"][0]["quote"] = None
    elif case == "unhashable licence":
        explain["criteria"][0]["source_references"][0]["licence"] = []
    elif case == "untyped locator":
        explain["criteria"][0]["source_references"][0]["locator"] = []
    elif case == "untyped keys":
        explain["criteria"][0]["source_refs"] = [None]
    elif case == "untyped identifier":
        explain["criteria"][0]["criterion_id"] = []
    elif case == "duplicate identifier":
        explain["criteria"][1]["criterion_id"] = explain["criteria"][0]["criterion_id"]
    transport = _transport_for(explain, decide, **kwargs)
    if case == "lost decision":
        def transport(url, *, method="GET", body=None):
            if method == "POST":
                raise OSError("synthetic lost response")
            return 200, explain
    with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
        manifest = _manifest(Path(tmpdir))
        manifest.manifest_path.write_text(yaml.safe_dump({"criteria": manifest.criteria}))
        artefact = cp.build_evidence([manifest], offline=False, base_url="https://staging.example.test", transport=transport, source_fetcher=_fetcher)
        json.dumps(artefact)  # malformed wire inputs must still yield a serializable report.
        row = artefact["showcases"][0]
        if case == "positive":
            assert row["claim_eligible"] is True
            assert row["served_by_path"] == {"explain": 2, "decide": 2}
            assert row["criteria_served_by_engine"] == 2 and row["served_coverage"] == 1.0
            path = Path(tmpdir) / "positive.json"
            path.write_text(json.dumps(artefact))
            assert cp.verify_artefact([manifest], path, "https://staging.example.test", transport=transport, source_fetcher=_fetcher) == 0
            assert cp.verify_artefact([manifest], path, "https://staging.example.test", transport=_transport_for(explain, {"explanation": None}), source_fetcher=_fetcher) == 1
        else:
            assert row["claim_eligible"] is False
            assert row["criteria_served_by_engine"] is None and row["served_coverage"] is None
            assert artefact["totals"]["showcases_claim_eligible"] == 0
            assert row["failures"] and all(f["showcase"] == manifest.name for f in row["failures"])
            if case in ("null decision", "failed decision", "partial decision", "lost decision"):
                assert row["served_by_path"]["explain"] == 2


def test_recorded_corpus_paired_consumer(legacy: bool) -> None:
    import check_provenance as cp
    from lib.fetching import FetchedSource
    from urllib.parse import unquote
    manifests = [m for m in _real_manifests() if all(d.local_path for d in m.documents.values())]
    assert len(manifests) == 4
    payloads = {m.ruleset_slug: json.loads(m.explain_fixture.read_text()) for m in manifests}
    if legacy:
        for payload in payloads.values():
            for criterion in payload["criteria"]:
                for reference in criterion["source_references"]:
                    reference.pop("snapshot", None)
    docs = _offline_fixture_documents(manifests, payloads)
    def transport(url, *, method="GET", body=None):
        slug = body["ruleset_id"] if method == "POST" else unquote(url.split("/rulesets/")[1].removesuffix("/explain"))
        payload = payloads[slug]
        # Adapt retained criterion data into the owning decide envelope for this
        # offline consumer control; this is not a captured/live decide receipt.
        return (200, __import__("tests.fixtures_probe", fromlist=["_decide_payload"])._decide_payload(payload)) if method == "POST" else (200, payload)
    def fetch(url):
        doc = docs[url]
        return FetchedSource(url=url, content=(ROOT / doc.local_path).read_bytes(), media_type=doc.media_type)
    artefact = cp.build_evidence(manifests, offline=False, base_url="https://staging.example.test", transport=transport, source_fetcher=fetch)
    # Every committed fixture is now a current served cut, digest-bound to its
    # local source, so all four showcases pair cleanly offline.
    assert artefact["totals"]["criteria_served_by_engine"] == 30
    assert artefact["totals"]["showcases_claim_eligible"] == 4
    for row in artefact["showcases"]:
        assert row["claim_eligible"] is True
        assert row["served_by_path"] == {"explain": row["criteria_total"], "decide": row["criteria_total"]}


def test_main_cli_reports_observed_failures(case: str) -> None:
    import check_provenance as cp
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher, _transport_for
    explain, decide = _payload(), _decide_payload()
    if case == "null decision":
        decide["explanation"] = None
    elif case == "malformed reference":
        explain["criteria"][0]["source_references"] = [None]
    with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
        manifest = _manifest(Path(tmpdir))
        manifest.manifest_path.write_text(yaml.safe_dump({"criteria": manifest.criteria}))
        output = Path(tmpdir) / "cli.json"
        with patch.object(cp, "load_registry", return_value=[manifest]), patch.object(cp, "_http_json", _transport_for(explain, decide)), patch.object(cp, "fetch_source", _fetcher), patch.object(sys, "argv", ["check_provenance", "--base-url", "https://staging.example.test", "--json", str(output)]):
            if case == "positive":
                cp.main()
            else:
                try:
                    cp.main()
                except SystemExit as exc:
                    assert exc.code == 1
                else:
                    raise AssertionError("owning CLI accepted broken decision evidence")
        artefact = json.loads(output.read_text())
        assert artefact["showcases"][0]["claim_eligible"] is (case == "positive")


def test_publisher_malformed_candidate_is_diagnosed() -> None:
    import publish_showcase as publisher
    from tests.fixtures_probe import _manifest
    with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
        manifest = _manifest(Path(tmpdir))
        for criteria in ([None], [42], [{"criterion_id": [], "source_refs": []}], [{"criterion_id": "a", "source_refs": [None]}]):
            expect_raises(publisher.PublishRefused, lambda c=criteria: publisher.gate(manifest, c))
        for response in (None, [], 42):
            expect_raises(publisher.PublishRefused, lambda r=response: publisher._assert_candidate_matches(manifest, r, "selftest"))


def _producer_http(explain: dict, decide: dict):
    """Inject actual JSON HTTP responses while exercising owning dispatch."""
    class Response:
        headers = {}
        status = 200
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, amt=None):
            return json.dumps(self.payload).encode()
    def open_response(request, *, timeout):
        assert timeout == 30.0
        if request.get_method() == "POST":
            sent = json.loads(request.data)
            assert sent["include_explanation"] is True and sent["field_values"] == {}
            return Response(decide)
        assert request.get_method() == "GET" and request.full_url.endswith("/explain")
        return Response(explain)
    return open_response


def test_identity_consumers_actual_http(case: str) -> None:
    import check_provenance as cp
    import probe_staging as probe
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher
    explain, decide = _payload(), _decide_payload()
    positive = case in ("alias positive", "immutable ID positive", "not eligible positive", "blocking override positive", "optional timing null positive")
    if case == "wrong alias":
        decide["slug"] = "aethis/other"
    elif case == "different ID":
        decide["ruleset_id"] = "different:20260913-aaaa"
    elif case == "different version":
        decide["ruleset_version"] = "v2"
    elif case == "different digest":
        decide["content_digest"] = "sha256:" + "b" * 64
    elif case == "missing identity":
        for field in cp.IDENTITY_FIELDS:
            decide.pop(field)
    elif case == "missing decision":
        decide.pop("decision")
    elif case == "null decision":
        decide["decision"] = None
    elif case == "malformed decision":
        decide["decision"] = []
    elif case == "nested decision mismatch":
        decide["decision"] = "eligible"
        decide["explanation"]["decision"] = "not_eligible"
    elif case == "slug as resolved ID":
        explain["ruleset_id"] = decide["ruleset_id"] = explain["slug"]
    elif case == "missing rule_text":
        explain["criteria"][0].pop("rule_text")
    elif case == "malformed rule_text":
        explain["criteria"][0]["rule_text"] = []
    elif case == "missing criterion status":
        decide["explanation"]["groups"][0]["criteria"][0].pop("status")
    elif case == "malformed group status":
        decide["explanation"]["groups"][0]["status"] = []
    elif case == "missing nested decision":
        decide["explanation"].pop("decision")
    elif case == "missing unused_facts":
        decide["explanation"].pop("unused_facts")
    elif case == "missing decision_id":
        decide.pop("decision_id")
    elif case == "missing decision_time":
        decide.pop("decision_time")
    elif case == "missing engine_version":
        decide.pop("engine_version")
    elif case == "missing fields_evaluated":
        decide.pop("fields_evaluated")
    elif case == "wrong empty-input hash":
        decide["inputs_hash"] = "sha256:" + "b" * 64
    elif case == "wrong fields_provided":
        decide["fields_provided"] = 1
    elif case == "contradictory content_identity":
        decide["content_identity"] = "sha256:" + "c" * 64
    elif case == "contradictory rulebook identity":
        decide["rulebook_id"] = "other-rulebook"
    elif case == "blocking errors with terminal":
        decide["decision"] = decide["explanation"]["decision"] = "not_eligible"
        decide["field_errors"] = {"__evaluation__": "blocking"}
    elif case == "null total timing":
        decide["timing"] = {"total_ms": None}
    elif case.startswith("oversized timing "):
        decide["timing"] = {"total_ms": 12, case.removeprefix("oversized timing "): 10**400}
    elif case.startswith("unexplained undetermined "):
        decide["explanation"]["decision"] = case.removeprefix("unexplained undetermined ")
    elif case == "blocking override positive":
        decide["explanation"]["decision"] = "eligible"
        decide["field_errors"] = {"__evaluation__": "blocking"}
    elif case == "optional timing null positive":
        decide["timing"] = {"total_ms": 12, "compilation_ms": None, "evaluation_ms": None}
    elif case == "not eligible positive":
        decide["decision"] = decide["explanation"]["decision"] = "not_eligible"
    with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
        manifest = _manifest(Path(tmpdir))
        manifest.manifest_path.write_text(yaml.safe_dump({"criteria": manifest.criteria}))
        if case == "immutable ID positive":
            manifest.ruleset_slug = explain["ruleset_id"]
        with patch("urllib.request.urlopen", _producer_http(explain, decide)), patch.object(cp, "fetch_source", _fetcher), patch.object(probe, "fetch_source", _fetcher):
            artefact = cp.build_evidence([manifest], offline=False, base_url="https://staging.example.test")
            row = artefact["showcases"][0]
            assert row["claim_eligible"] is positive
            assert row["observations"]["decide"]["response"] == decide
            path = Path(tmpdir) / "artifact.json"
            path.write_text(json.dumps(artefact))
            assert cp.verify_artefact([manifest], path, "https://staging.example.test") == (0 if positive else 1)
            for cli in (cp, probe):
                output = Path(tmpdir) / (cli.__name__ + ".json")
                with patch.object(cli, "load_registry", return_value=[manifest]), patch.object(sys, "argv", [cli.__name__, "--base-url", "https://staging.example.test", "--json", str(output)]):
                    try:
                        cli.main()
                    except SystemExit as exc:
                        assert exc.code == (0 if positive else 1)
                    else:
                        assert positive
                report = json.loads(output.read_text())
                rows = report.get("showcases", report.get("results"))
                assert rows[0]["claim_eligible"] is positive
        if positive:
            # Identity remains substantive: an otherwise reference-identical
            # fresh cut cannot verify the retained artifact unchanged.
            changed = copy.deepcopy(decide)
            changed["content_digest"] = "sha256:" + "c" * 64
            with patch("urllib.request.urlopen", _producer_http(explain, changed)), patch.object(cp, "fetch_source", _fetcher):
                assert cp.verify_artefact([manifest], path, "https://staging.example.test") == 1


def test_real_source_read_failure_consumers(case: str) -> None:
    import check_provenance as cp
    import probe_staging as probe
    import publish_showcase as publisher
    import http.client
    from lib.fetching import fetch_source
    from tests.fixtures_probe import _manifest, _payload, _decide_payload
    explain, decide = _payload(), _decide_payload()
    failures = {"reset": ConnectionResetError(54, "reset"), "timeout": TimeoutError("read timeout"), "incomplete": http.client.IncompleteRead(b"partial")}
    class SourceResponse:
        status = 200
        headers = {"content-type": "text/plain"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, cap):
            assert cap == 10 * 1024 * 1024 + 1
            raise failures[case]
    class Opener:
        calls = 0
        def open(self, request, *, timeout):
            self.calls += 1
            assert timeout == 15.0
            return SourceResponse()
    opener = Opener()
    def failed_fetch(url):
        return fetch_source(url, resolver=lambda host: ["8.8.8.8"], opener=opener)
    with tempfile.TemporaryDirectory(dir=ROOT) as tmpdir:
        manifest = _manifest(Path(tmpdir))
        manifest.manifest_path.write_text(yaml.safe_dump({"criteria": manifest.criteria}))
        with patch("urllib.request.urlopen", _producer_http(explain, decide)), patch.object(cp, "fetch_source", failed_fetch), patch.object(probe, "fetch_source", failed_fetch):
            artefact = cp.build_evidence([manifest], offline=False, base_url="https://staging.example.test")
            assert opener.calls == 1  # one bounded source attempt, reused on both paths.
            assert artefact["showcases"][0]["claim_eligible"] is False
            assert {f["reason_code"] for f in artefact["failures"]} & {"fetch_failure", "fetch_timeout"}
            path = Path(tmpdir) / "artifact.json"
            path.write_text(json.dumps(artefact))
            assert cp.verify_artefact([manifest], path, "https://staging.example.test") == 1
            for cli in (cp, probe):
                output = Path(tmpdir) / (cli.__name__ + ".json")
                with patch.object(cli, "load_registry", return_value=[manifest]), patch.object(sys, "argv", [cli.__name__, "--base-url", "https://staging.example.test", "--json", str(output)]):
                    try:
                        cli.main()
                    except SystemExit as exc:
                        assert exc.code == 1
                    else:
                        raise AssertionError("source failure accepted")
                assert output.is_file() and json.loads(output.read_text())["failures"]
            expect_raises(publisher.PublishRefused, lambda: publisher.gate(manifest, explain["criteria"]))
        with patch.object(cp, "fetch_source", lambda url: (_ for _ in ()).throw(ValueError("programming error"))):
            expect_raises(ValueError, lambda: cp.check_showcase(manifest, offline=False, live_explain=explain))


def test_real_http_source_length_contract(extra: int) -> None:
    import http.client
    import io
    import check_provenance as cp
    import publish_showcase as publisher
    import probe_staging as probe
    from lib.fetching import fetch_source
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, DOC_BYTES
    class Socket:
        def makefile(self, mode):
            return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: ' + str(len(DOC_BYTES) + extra).encode() + b'\r\n\r\n' + DOC_BYTES)
    class Opener:
        def open(self, request, *, timeout):
            response = http.client.HTTPResponse(Socket())
            response.begin()
            return response
    def read_source(url):
        return fetch_source(url, resolver=lambda host: ['8.8.8.8'], opener=Opener())
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        manifest = _manifest(Path(directory))
        manifest.manifest_path.write_text(yaml.safe_dump({'criteria': manifest.criteria}))
        explain, decide = _payload(), _decide_payload()
        with patch('urllib.request.urlopen', _producer_http(explain, decide)), patch.object(cp, 'fetch_source', read_source), patch.object(probe, 'fetch_source', read_source):
            artifact = cp.build_evidence([manifest], offline=False, base_url='https://staging.example.test')
            assert artifact['showcases'][0]['claim_eligible'] is (extra == 0)
            path = Path(directory) / 'artifact.json'
            path.write_text(json.dumps(artifact))
            assert cp.verify_artefact([manifest], path, 'https://staging.example.test') == (0 if extra == 0 else 1)
            for cli in (cp, probe):
                output = Path(directory) / (cli.__name__ + '.json')
                with patch.object(cli, 'load_registry', return_value=[manifest]), patch.object(sys, 'argv', [cli.__name__, '--base-url', 'https://staging.example.test', '--json', str(output)]):
                    try:
                        cli.main()
                    except SystemExit as exc:
                        assert exc.code == (1 if extra else 0)
                    else:
                        assert extra == 0
                assert output.is_file()
            if extra:
                assert 'incomplete_response' in {f['reason_code'] for f in artifact['failures']}
                expect_raises(publisher.PublishRefused, lambda: publisher.gate(manifest, explain['criteria']))
            else:
                assert not publisher.gate(manifest, explain['criteria'])['failures']


def test_artifact_invocation_variance_is_validated_before_comparison() -> None:
    import check_provenance as cp
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher, _transport_for
    explain, decide = _payload(), _decide_payload()
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        manifest = _manifest(Path(directory))
        manifest.manifest_path.write_text(yaml.safe_dump({'criteria': manifest.criteria}))
        original = cp.build_evidence([manifest], offline=False, base_url='https://staging.example.test', transport=_transport_for(explain, decide), source_fetcher=_fetcher)
        path = Path(directory) / 'artifact.json'
        path.write_text(json.dumps(original))
        later = copy.deepcopy(decide)
        later['decision_id'] = 'dec_different0000000'
        later['decision_time'] = '2026-09-13T14:00:00Z'
        later['timing'] = {'total_ms': 123}
        assert cp.verify_artefact([manifest], path, 'https://staging.example.test', transport=_transport_for(explain, later), source_fetcher=_fetcher) == 0
        for field in ('decision_id', 'decision_time'):
            forged = copy.deepcopy(original)
            forged['showcases'][0]['observations']['decide']['response'].pop(field)
            path.write_text(json.dumps(forged))
            assert cp.verify_artefact([manifest], path, 'https://staging.example.test', transport=_transport_for(explain, later), source_fetcher=_fetcher) == 1


def test_quote_context_is_observed_not_just_link_construction() -> None:
    from dataclasses import replace
    import check_provenance as cp
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher, _transport_for, DOC_BYTES
    assert quote_occurs(Quote(exact='must hold a valid widget licence.', prefix='An applicant'), DOC_BYTES, MEDIA_TEXT)
    assert not quote_occurs(Quote(exact='must hold a valid widget licence.', prefix='fabricated'), DOC_BYTES, MEDIA_TEXT)
    assert not quote_occurs(Quote(exact='must hold a valid widget licence.', suffix='fabricated'), DOC_BYTES, MEDIA_TEXT)
    assert quote_occurs(Quote(exact='target', prefix='real', suffix='context'), b'fake target nowhere; real\n target\tcontext', MEDIA_TEXT)
    for prefix, suffix in (('absent prefix', None), (None, 'absent suffix')):
        with tempfile.TemporaryDirectory() as directory:
            manifest = _manifest(Path(directory))
            key = 'ACT#S1'
            q = replace(manifest.references[key].quote, prefix=prefix, suffix=suffix)
            manifest.references[key] = replace(manifest.references[key], quote=q)
            explain, decide = _payload(), _decide_payload()
            for criterion in (explain['criteria'][0], decide['explanation']['groups'][0]['criteria'][0]):
                criterion['source_references'][0]['quote'] = q.as_wire()
                criterion['source_references'][0]['deep_link'] = build_deep_link('https://example.test/authority/act.md', q, MEDIA_TEXT)
            row = cp.probe_showcase(manifest, base_url='https://staging.example.test', fetcher=_fetcher, transport=_transport_for(explain, decide))
            assert row['claim_eligible'] is False
            assert 'quote_not_found' in {f['reason_code'] for f in row['failures']}


def test_unavailable_explain_reuses_single_paired_source_cache() -> None:
    import check_provenance as cp
    import probe_staging as probe
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher
    for status in (206, 503, 'reset'):
        for unavailable_source in (False, True):
            count = []
            def source(url):
                count.append(url)
                if unavailable_source:
                    raise TargetSafetyError('fetch_failure', 'injected unavailable source')
                return _fetcher(url)
            normal = _producer_http(_payload(), _decide_payload())
            def open_response(request, *, timeout):
                if request.get_method() == 'GET':
                    if status == 'reset':
                        raise ConnectionResetError('injected explain reset')
                    response = normal(request, timeout=timeout)
                    response.status = status
                    return response
                return normal(request, timeout=timeout)
            with tempfile.TemporaryDirectory(dir=ROOT) as directory:
                manifest = _manifest(Path(directory))
                manifest.manifest_path.write_text(yaml.safe_dump({'criteria': manifest.criteria}))
                with patch('urllib.request.urlopen', open_response), patch.object(cp, 'fetch_source', source), patch.object(probe, 'fetch_source', source):
                    artifact = cp.build_evidence([manifest], offline=False, base_url='https://staging.example.test')
                    assert len(count) == 1 and artifact['showcases'][0]['claim_eligible'] is False
                    path = Path(directory) / 'artifact.json'
                    path.write_text(json.dumps(artifact))
                    assert cp.verify_artefact([manifest], path, 'https://staging.example.test') == 1
                    assert len(count) == 2
                    for cli in (cp, probe):
                        output = Path(directory) / (cli.__name__ + '.json')
                        before = len(count)
                        with patch.object(cli, 'load_registry', return_value=[manifest]), patch.object(sys, 'argv', [cli.__name__, '--base-url', 'https://staging.example.test', '--json', str(output)]):
                            expect_raises(SystemExit, cli.main)
                        assert len(count) == before + 1 and output.is_file()


def test_endpoint_code_error_remains_visible() -> None:
    import check_provenance as cp
    from tests.fixtures_probe import _manifest
    class Response:
        headers = {}
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, amt=None):
            raise NameError('sentinel programming bug')
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        manifest = _manifest(Path(directory))
        with patch('urllib.request.urlopen', return_value=Response()):
            expect_raises(NameError, lambda: cp.build_evidence([manifest], offline=False, base_url='https://staging.example.test'))


def test_remote_candidate_expected_failures_and_contract() -> None:
    import publish_showcase as publisher
    from tests.fixtures_probe import _manifest, _payload
    class Response:
        headers = {}
        def __init__(self, case):
            self.case = case
            self.status = 206 if case == 'partial' else 503 if case == 'http' else 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, amt=None):
            if self.case == 'reset':
                raise ConnectionResetError('read reset')
            if self.case == 'timeout':
                raise TimeoutError('read timeout')
            if self.case == 'invalid JSON':
                return b'not-json'
            return json.dumps({'slug': 'aethis/synthetic', 'criteria': _payload()['criteria']} if self.case == 'slug only' else _payload()).encode()
    with tempfile.TemporaryDirectory() as directory:
        manifest = _manifest(Path(directory))
        for case in ('positive', 'partial', 'http', 'reset', 'timeout', 'invalid JSON', 'slug only'):
            with patch('urllib.request.urlopen', return_value=Response(case)):
                if case == 'positive':
                    assert publisher.load_expected_explanation(manifest, 'https://example.test/candidate')['ruleset_id'] == _payload()['ruleset_id']
                else:
                    expect_raises(publisher.PublishRefused, lambda: publisher.load_expected_explanation(manifest, 'https://example.test/candidate'))


def test_json_decoder_boundary_consumers(case: str) -> None:
    import io
    import http.client
    import urllib.error
    import check_provenance as cp
    import publish_showcase as publisher
    import probe_staging as probe
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher
    huge = b'1' + b'0' * 5000
    explain, decide = _payload(), _decide_payload()
    if case == 'nesting':
        raw = b'[' * 50000 + b'0' + b']' * 50000
    elif case == 'nested invalid observation':
        raw = b'[' * 2000 + b'0' + b']' * 2000
    elif case == 'positive':
        raw = json.dumps(decide).encode()
    else:
        raw = json.dumps(decide).encode()[:-1] + b', "timing": {"total_ms": ' + huge + b'}}'
    class Socket:
        def makefile(self, mode):
            return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(raw)).encode() + b'\r\n\r\n' + raw)
    class Response(http.client.HTTPResponse):
        def __init__(self):
            super().__init__(Socket())
            self.begin()
        def read(self, amt=None):
            if case == 'reader code error':
                raise ValueError('sentinel reader programming error')
            return super().read(amt)
    def open_response(request, **kwargs):
        if request.get_method() == 'GET' and case not in ('explain', 'HTTP error', 'reader code error'):
            return _producer_http(explain, decide)(request, **kwargs)
        if case == 'HTTP error':
            raise urllib.error.HTTPError(request.full_url, 503, 'unavailable', {}, io.BytesIO(raw))
        return Response()
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        manifest = _manifest(Path(directory))
        manifest.manifest_path.write_text(yaml.safe_dump({'criteria': manifest.criteria}))
        path = Path(directory) / 'artifact.json'
        if case in ('local preview', 'default preview', 'remote preview'):
            path.write_bytes(raw)
            with patch('urllib.request.urlopen', side_effect=lambda *args, **kwargs: Response()):
                if case == 'default preview':
                    manifest.explain_fixture.write_bytes(raw)
                    selector = None
                else:
                    selector = 'https://example.test/candidate' if case == 'remote preview' else str(path)
                expect_raises(publisher.PublishRefused, lambda: publisher.load_expected_explanation(manifest, selector))
            return
        with patch('urllib.request.urlopen', open_response), patch.object(cp, 'fetch_source', _fetcher), patch.object(probe, 'fetch_source', _fetcher):
            if case == 'reader code error':
                expect_raises(ValueError, lambda: cp.build_evidence([manifest], offline=False, base_url='https://staging.example.test'))
                return
            if case == 'stored artifact':
                path.write_bytes(raw)
                assert cp.verify_artefact([manifest], path, 'https://staging.example.test') == 1
                return
            artifact = cp.build_evidence([manifest], offline=False, base_url='https://staging.example.test')
            assert artifact['showcases'][0]['claim_eligible'] is (case == 'positive')
            path.write_text(json.dumps(artifact))
            assert cp.verify_artefact([manifest], path, 'https://staging.example.test') == (0 if case == 'positive' else 1)
            for cli in (cp, probe):
                output = Path(directory) / (cli.__name__ + '.json')
                with patch.object(cli, 'load_registry', return_value=[manifest]), patch.object(sys, 'argv', [cli.__name__, '--base-url', 'https://staging.example.test', '--json', str(output)]):
                    try:
                        cli.main()
                    except SystemExit as exc:
                        assert exc.code == (0 if case == 'positive' else 1)
                    else:
                        assert case == 'positive'
                assert output.is_file()
                report = json.loads(output.read_text())
                assert bool(report['failures']) is (case != 'positive')



def assert_system_exit(call: Callable, code: int) -> None:
    try:
        call()
    except SystemExit as exc:
        assert exc.code == code
    else:
        raise AssertionError("expected SystemExit")


def test_complete_json_http_consumers(case: str) -> None:
    import http.client
    import io
    import urllib.error
    import check_provenance as cp
    import probe_staging as probe
    import publish_showcase as publisher
    from lib.fetching import MAX_RESPONSE_BYTES
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher
    explain, decide = _payload(), _decide_payload()
    accepted = case in ('complete', 'complete padded', 'finite read')
    reads = []
    class Response(http.client.HTTPResponse):
        def __init__(self, payload):
            raw = json.dumps(payload).encode()
            extra = 0 if accepted else 50
            prefix = b'0' * 5000 if case not in ('short ordinary', 'complete') else b''
            header = prefix + str(len(raw) + extra).encode()
            class Socket:
                def makefile(self, mode):
                    return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: ' + header + b'\r\n\r\n' + raw)
            super().__init__(Socket())
            self.begin()
            if prefix:
                assert self.length is None
        def read(self, amt=None):
            reads.append(amt)
            return super().read(amt)
    def open_response(request, **kwargs):
        return Response(decide if request.get_method() == 'POST' else explain)
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        manifest = _manifest(Path(directory))
        manifest.manifest_path.write_text(yaml.safe_dump({'synthetic': True}))
        with patch('urllib.request.urlopen', open_response), patch.object(cp, 'fetch_source', _fetcher), patch.object(probe, 'fetch_source', _fetcher):
            result = cp.build_evidence([manifest], offline=False, base_url='https://example.test')
            assert result['showcases'][0]['claim_eligible'] is accepted
            artifact = Path(directory) / 'artifact.json'
            artifact.write_text(json.dumps(result))
            assert cp.verify_artefact([manifest], artifact, 'https://example.test') == (0 if accepted else 1)
            if accepted:
                assert cp.fetch_live_explain(manifest.ruleset_slug, 'https://example.test') == explain
                assert publisher.load_expected_explanation(manifest, 'https://example.test/candidate') == explain
            else:
                expect_raises(TargetSafetyError, lambda: cp.fetch_live_explain(manifest.ruleset_slug, 'https://example.test'))
                expect_raises(publisher.PublishRefused, lambda: publisher.load_expected_explanation(manifest, 'https://example.test/candidate'))
            for cli in (cp, probe):
                output = Path(directory) / (cli.__name__ + '.json')
                with patch.object(cli, 'load_registry', return_value=[manifest]), patch.object(sys, 'argv', [cli.__name__, '--base-url', 'https://example.test', '--json', str(output)]):
                    try:
                        cli.main()
                    except SystemExit as exc:
                        assert exc.code == (0 if accepted else 1)
                assert output.is_file() and bool(json.loads(output.read_text())['failures']) is (not accepted)
            with patch.object(cp, 'verify_artefact', wraps=cp.verify_artefact), patch.object(cp, 'load_registry', return_value=[manifest]), patch.object(sys, 'argv', ['checker', '--verify-artefact', '--json', str(artifact), '--base-url', 'https://example.test']):
                assert_system_exit(cp.main, 0 if accepted else 1)
        assert reads
        # HTTP error bodies share the same single bounded completeness reader.
        response = Response(explain)
        error = urllib.error.HTTPError('https://example.test', 503, 'unavailable', response.headers, response)
        with patch('urllib.request.urlopen', side_effect=error):
            if accepted:
                assert cp._http_json('https://example.test')[0] == 503
            else:
                expect_raises(TargetSafetyError, lambda: cp._http_json('https://example.test'))
        if case == 'finite read':
            assert reads and all(amt == MAX_RESPONSE_BYTES + 1 for amt in reads)


def test_whole_artifact_bounds(case: str) -> None:
    import check_provenance as cp
    import probe_staging as probe
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher
    explain, decide = _payload(), _decide_payload()
    accepted = case == 'positive'
    extra = 0
    for _ in range(32 if accepted else 600):
        extra = [extra]
    if case == 'node bound':
        extra = [0] * 100_001
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        manifest = _manifest(Path(directory))
        manifest.manifest_path.write_text(yaml.safe_dump({'synthetic': True}))
        with patch('urllib.request.urlopen', _producer_http(explain, decide)), patch.object(cp, 'fetch_source', _fetcher), patch.object(probe, 'fetch_source', _fetcher):
            artifact = cp.build_evidence([manifest], offline=False, base_url='https://example.test')
            path = Path(directory) / 'artifact.json'
            path.write_text(json.dumps(artifact))
            assert cp.verify_artefact([manifest], path, 'https://example.test') == 0
            if case in ('retained response', 'live response'):
                artifact['showcases'][0]['observations']['decide']['response']['extra'] = extra
            else:
                artifact['extra'] = extra
            path.write_text(json.dumps(artifact))
            # The old copier fails on a deep but otherwise valid envelope.
            if not accepted:
                assert cp.verify_artefact([manifest], path, 'https://example.test') == 1
                with patch.object(cp, 'build_evidence', side_effect=AssertionError('unbounded artifact must refuse before fresh observation')):
                    assert cp.verify_artefact([manifest], path, 'https://example.test') == 1
                with patch.object(cp, 'load_registry', return_value=[manifest]), patch.object(sys, 'argv', ['checker', '--verify-artefact', '--json', str(path), '--base-url', 'https://example.test']):
                    assert_system_exit(cp.main, 1)
            if case in ('positive', 'live response'):
                decide['extra'] = extra
                for transport in (None, lambda url, **kwargs: (200, decide if kwargs else explain)):
                    result = cp.build_evidence([manifest], offline=False, base_url='https://example.test', transport=transport, source_fetcher=_fetcher)
                    assert result['showcases'][0]['claim_eligible'] is accepted
                    json.dumps(result)
                for cli in (cp, probe):
                    output = Path(directory) / (cli.__name__ + '.json')
                    with patch.object(cli, 'load_registry', return_value=[manifest]), patch.object(sys, 'argv', [cli.__name__, '--base-url', 'https://example.test', '--json', str(output)]):
                        try:
                            cli.main()
                        except SystemExit as exc:
                            assert exc.code == (0 if accepted else 1)
                    assert output.is_file() and bool(json.loads(output.read_text())['failures']) is (not accepted)



def test_assembled_artifact_bounds(case: str) -> None:
    import check_provenance as cp
    from lib.json_decode import decode_json, validate_json_tree
    from tests.fixtures_probe import _manifest, _payload, _decide_payload, _fetcher, _transport_for
    explain, decide = _payload(), _decide_payload()
    if case == 'depth aggregation':
        extra = 0
        for _ in range(63):
            extra = [extra]
        decide['extra'] = extra
    elif case == 'node aggregation':
        explain['extra'] = [0] * 60_000
        decide['extra'] = [0] * 60_000
    validate_json_tree(explain)
    validate_json_tree(decide)
    accepted = case == 'normal'
    transport = _transport_for(explain, decide)
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        manifest = _manifest(Path(directory))
        manifest.manifest_path.write_text('synthetic: true\n')
        artifact = cp.build_evidence([manifest], offline=False, base_url='https://example.test', transport=transport, source_fetcher=_fetcher)
        assert artifact['showcases'][0]['claim_eligible'] is accepted
        assert bool(artifact['failures']) is (not accepted)
        validate_json_tree(artifact)
        path = Path(directory) / 'artifact.json'
        path.write_text(json.dumps(artifact))
        decode_json(path.read_text())
        assert cp.verify_artefact([manifest], path, 'https://example.test', transport=transport, source_fetcher=_fetcher) == (0 if accepted else 1)
        with patch.object(cp, 'load_registry', return_value=[manifest]), patch.object(cp, '_http_json', transport), patch.object(cp, 'fetch_source', _fetcher), patch.object(sys, 'argv', ['checker', '--base-url', 'https://example.test', '--json', str(path)]):
            from contextlib import redirect_stdout, redirect_stderr
            import io
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                try:
                    cp.main()
                except SystemExit as exc:
                    assert exc.code == (0 if accepted else 1)
                else:
                    assert accepted
        emitted = decode_json(path.read_text())
        assert emitted['showcases'][0]['claim_eligible'] is accepted
        assert ('PASS' in output.getvalue()) is accepted
        assert bool(emitted['failures']) is (not accepted)
        assert cp.verify_artefact([manifest], path, 'https://example.test', transport=transport, source_fetcher=_fetcher) == (0 if accepted else 1)


def test_source_length_header_consumers(case: str) -> None:
    import http.client
    import io
    import check_provenance as cp
    import publish_showcase as publisher
    import probe_staging as probe
    from lib.fetching import fetch_source
    from tests.fixtures_probe import _decide_payload
    manifest = next(m for m in _real_manifests() if m.name == 'consumer-credit-prequalification')
    doc = next(iter(manifest.documents.values()))
    DOC_BYTES = (ROOT / doc.local_path).read_bytes()
    assert len(DOC_BYTES) == 7390  # Unchanged retained source, not invented quote material.
    explain = json.loads(manifest.explain_fixture.read_text())
    # Retained explain criteria adapted into decide envelope, offline only.
    decide = _decide_payload(explain)
    length = str(len(DOC_BYTES)).encode()
    headers = {'positive': length, 'space': length + b' ', 'tab': length + b'\t',
               'leading zeros': b'0' * 5000 + length, 'short body': str(len(DOC_BYTES) + 50).encode(),
               'huge': b'1' + b'0' * 5000, 'non ASCII': b'\xb2', 'malformed': b'12x',
               'negative': b'-1', 'empty': b' ', 'no header': None, 'lower cap': length,
               'excess body': None}
    accepted = case in ('positive', 'space', 'tab', 'leading zeros', 'no header')
    cap = len(DOC_BYTES) - 1 if case == 'lower cap' else len(DOC_BYTES) if case == 'excess body' else len(DOC_BYTES) + 100
    body = DOC_BYTES + b'x' if case == 'excess body' else DOC_BYTES
    class Socket:
        def makefile(self, mode):
            header = b'' if headers[case] is None else b'Content-Length: ' + headers[case] + b'\r\n'
            return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n' + header + b'\r\n' + body)
    class Opener:
        def open(self, request, *, timeout):
            response = http.client.HTTPResponse(Socket())
            response.begin()
            return response
    def source(url):
        return fetch_source(url, max_bytes=cap, resolver=lambda host: ['8.8.8.8'], opener=Opener())
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        with patch('urllib.request.urlopen', _producer_http(explain, decide)), patch.object(cp, 'fetch_source', source), patch.object(probe, 'fetch_source', source):
            artifact = cp.build_evidence([manifest], offline=False, base_url='https://staging.example.test')
            assert artifact['showcases'][0]['claim_eligible'] is accepted
            path = Path(directory) / 'artifact.json'
            path.write_text(json.dumps(artifact))
            assert cp.verify_artefact([manifest], path, 'https://staging.example.test') == (0 if accepted else 1)
            for cli in (cp, probe):
                output = Path(directory) / (cli.__name__ + '.json')
                with patch.object(cli, 'load_registry', return_value=[manifest]), patch.object(sys, 'argv', [cli.__name__, '--base-url', 'https://staging.example.test', '--json', str(output)]):
                    try:
                        cli.main()
                    except SystemExit as exc:
                        assert exc.code == (0 if accepted else 1)
                    else:
                        assert accepted
                assert output.is_file()
                assert bool(json.loads(output.read_text())['failures']) is (not accepted)
            if accepted:
                assert not publisher.gate(manifest, explain['criteria'])['failures']
            else:
                expect_raises(publisher.PublishRefused, lambda: publisher.gate(manifest, explain['criteria']))


def test_network_guard_detects_swallowed_attempt() -> None:
    import urllib.request
    def attempt():
        with deny_network():
            try:
                urllib.request.urlopen("https://must-never-be-accessed.invalid")
            except AssertionError:
                pass
    expect_raises(AssertionError, attempt)


def _run_checks() -> int:
    check("quote: whitespace normalised on both sides", test_whitespace_is_normalised_on_both_sides)
    check("quote: html tag-stripped, text is not", test_html_is_tag_stripped_but_text_is_not)
    check("quote: script/style content removed for html", test_script_and_style_content_is_removed_for_html)
    check("quote: case- and order-sensitive", test_matching_is_case_sensitive_and_order_sensitive)
    check("quote: paraphrase does not match", test_paraphrase_does_not_match)
    check("quote: empty quote never matches", test_empty_quote_never_matches)
    check("quote: undecodable bytes do not crash", test_undecodable_bytes_do_not_crash_the_check)
    check("quote: content-type maps to media type", test_media_type_mapping)
    check("quote: stripping applies only to html", test_searchable_text_strips_only_for_html)
    check("quote: unparseable pdf fails closed", test_unparseable_pdf_fails_closed)
    check("quote: missing pdf extractor fails closed", test_missing_pdf_extractor_raises_rather_than_passing)
    check("link: text fragment and page forms", test_deep_link_forms)
    check("link: markup in a quote is percent-encoded", test_deep_link_percent_encodes_markup_in_the_quote)

    check("target: non-https refused", test_non_https_schemes_are_refused)
    check("target: credentials refused", test_credentials_in_url_are_refused)
    check("target: ip literals refused", test_ip_literal_hosts_are_refused_including_encodings)
    check("target: non-default port refused", test_non_default_port_is_refused)
    check("target: private destinations refused", test_private_destinations_are_refused_after_dns)
    check("target: public destination accepted", test_public_destination_is_accepted)
    check("target: any private address in the set refuses", test_mixed_resolution_is_refused_if_any_address_is_private)
    check("target: normalisation drops the fragment", test_url_normalisation_drops_the_fragment)

    check("manifest: unallowlisted licence refused", test_unallowlisted_licence_is_refused)
    check("manifest: missing licence refused", test_missing_licence_is_refused)
    check("manifest: dangling document refused", test_dangling_document_reference_is_refused)
    check("manifest: dangling citation key refused", test_dangling_citation_key_is_refused)
    check("manifest: criterion with no keys refused", test_criterion_with_no_citation_keys_is_refused)
    check("manifest: malformed digest refused", test_malformed_digest_is_refused)
    check("manifest: forbidden content refused", test_forbidden_content_is_refused)
    check("manifest: wrong schema version refused", test_wrong_schema_version_is_refused)

    check("gate: real manifests are clean", test_real_manifests_are_structurally_clean)
    check("gate: removing a citation turns it RED", test_removing_one_criterion_citation_turns_the_gate_red)
    check("gate: stale criterion turns it RED", test_citing_a_criterion_the_ruleset_no_longer_evaluates_turns_the_gate_red)
    check("gate: unpinned document turns it RED", test_unpinned_document_turns_the_gate_red)
    check("gate: every evaluated criterion is cited", test_every_showcase_covers_every_criterion_the_engine_evaluates)

    check("live: denominator comes from the engine, not the fixture", test_denominator_comes_from_the_live_response_not_the_fixture)
    check("live: a short fixture cannot shrink the total", test_removing_a_criterion_from_the_fixture_cannot_shrink_the_total)
    check("live: fixture disagreeing with the engine is reported", test_fixture_disagreeing_with_the_engine_is_reported)
    check("offline: no verified count is produced", test_offline_reports_no_verified_count)
    check("live: served coverage is unverified without a live read", test_served_coverage_is_unverified_without_a_live_response)
    check("live: forged fixture cannot make a showcase eligible", test_forged_fixture_references_cannot_make_a_showcase_eligible)
    check("live: manifest keys must match declared keys", test_manifest_keys_must_match_the_keys_the_ruleset_declares)
    check("corpus: locally edited source turns it RED", test_locally_edited_corpus_turns_the_gate_red)
    check("corpus: every self-cited doc declares local_path", test_every_self_cited_document_declares_a_local_path)
    check("registry: a deleted showcase turns it RED", test_registry_cannot_lose_a_showcase_silently)
    check("boundary: plaintext, named, inflection-covering", test_restricted_boundary_is_plaintext_named_and_inflection_covering)
    check("boundary: missing list fails closed", test_missing_boundary_list_fails_closed)
    check("boundary: corpus files are swept, not just quotes", test_corpus_files_are_scanned_not_just_quoted_passages)
    check("artefact: a tampered artefact is rejected", test_a_tampered_evidence_artefact_is_rejected)
    check("artefact: volatile fields excluded, nothing else", test_volatile_fields_are_excluded_but_nothing_else_is)

    for status in (200, 201, 204, 206):
        check(f"live: complete HTTP status {status}", lambda v=status: test_live_http_status_is_complete(v))
    check("served: existing recorded publication is positive", test_recorded_served_references_are_a_genuine_positive_control)
    check("served: legacy v1 omitted snapshot is positive", test_legacy_v1_references_without_snapshot_are_valid)
    check("served: v1 URL referent markers remain positive", test_v1_url_referent_markers_are_legitimate_positive_controls)
    check("served: all online unserved criteria are RED", test_online_all_unserved_criteria_fail_closed)
    check("publish: prefix rejected, candidate identity preserved", test_publisher_rejects_prefix_identity_and_preserves_candidate)
    check("publish: apply refuses without network or credentials", test_publisher_apply_refuses_before_any_network_or_credential)
    mutations = {
        "missing resolved references": lambda c: c.pop("source_references"),
        "empty resolved references": lambda c: c.update(source_references=[]),
        "malformed resolved references": lambda c: c.update(source_references=[None]),
        "extra resolved reference": lambda c: c["source_references"].append(copy.deepcopy(c["source_references"][0])),
        "wrong citation key": lambda c: c["source_references"][0].update(source_id="another-key"),
        "wrong declared key": lambda c: c.update(source_refs=["another-key"]),
        "missing declared keys": lambda c: c.update(source_refs=[]),
        "wrong digest": lambda c: c["source_references"][0].update(content_digest="sha256:" + "0" * 64),
        "fabricated authority": lambda c: c["source_references"][0].update(authority="Fabricated authority"),
        "wrong quote": lambda c: c["source_references"][0]["quote"].update(exact="A different passage"),
        "wrong quote context": lambda c: c["source_references"][0]["quote"].update(prefix="Fabricated context"),
        "wrong URL": lambda c: c["source_references"][0].update(url="https://example.test/other"),
        "wrong licence": lambda c: c["source_references"][0].update(licence="All rights reserved"),
        "wrong source version": lambda c: c["source_references"][0].update(source_version="another version"),
        "wrong source date": lambda c: c["source_references"][0].update(source_date="1900-01-01"),
        "wrong locator": lambda c: c["source_references"][0].update(locator="another passage"),
        "wrong title": lambda c: c["source_references"][0].update(title="Another document"),
        "wrong media type": lambda c: c["source_references"][0].update(media_type="html"),
        "artefact target on v1": lambda c: c["source_references"][0].update(target_kind="artefact"),
        "artefact project on v1": lambda c: c["source_references"][0].update(artefact_project_id="foreign-project"),
        "artefact source on v1": lambda c: c["source_references"][0].update(artefact_source_id="foreign-source"),
        "non-string artefact ID on v1": lambda c: c["source_references"][0].update(artefact_source_id=0),
        "wrong snapshot": lambda c: c["source_references"][0].update(snapshot="sha256:" + "0" * 64),
        "wrong deep link": lambda c: c["source_references"][0].update(deep_link="https://example.test/other"),
        "unsupported schema": lambda c: c["source_references"][0].update(schema_version=2),
        "missing verification time": lambda c: c["source_references"][0].pop("verified_at"),
    }
    for name, mutate in mutations.items():
        check(f"served: {name} turns it RED", lambda m=mutate: test_served_reference_mutation(m))
    check("served: quote whitespace matches existing semantics", test_served_quote_whitespace_uses_existing_matching_semantics)
    check("served: changed source bytes remain RED", test_source_drift_still_fails_before_served_certification)
    check("served: offline recorded references remain unknown", test_offline_recorded_references_do_not_supply_verified_coverage)
    check("publish: candidate preflight cannot certify served evidence", test_candidate_publish_preflight_never_claims_served_evidence)

    for case in ("positive", "null decision", "failed decision", "partial decision", "divergent decision", "lost decision", "null explain criterion", "null decision criterion", "null reference", "null quote", "unhashable licence", "untyped locator", "untyped keys", "untyped identifier", "duplicate identifier"):
        check(f"consumer: {case}", lambda c=case: test_main_consumer_observes_both_paths(c))
    for legacy in (False, True):
        check(f"consumer: recorded corpus paired legacy={legacy}", lambda v=legacy: test_recorded_corpus_paired_consumer(v))
    for case in ("positive", "null decision", "malformed reference"):
        check(f"CLI: {case}", lambda c=case: test_main_cli_reports_observed_failures(c))
    check("publish: malformed candidate diagnosed before fetch", test_publisher_malformed_candidate_is_diagnosed)
    for case in ("alias positive", "immutable ID positive", "not eligible positive", "wrong alias", "different ID", "different version", "different digest", "missing identity", "missing decision", "null decision", "malformed decision", "nested decision mismatch", "slug as resolved ID", "missing rule_text", "malformed rule_text", "missing criterion status", "malformed group status", "missing nested decision", "missing unused_facts", "missing decision_id", "missing decision_time", "missing engine_version", "missing fields_evaluated", "wrong empty-input hash", "wrong fields_provided", "contradictory content_identity", "contradictory rulebook identity", "blocking errors with terminal"):
        check(f"identity HTTP+CLIs: {case}", lambda c=case: test_identity_consumers_actual_http(c))
    for case in ("reset", "timeout", "incomplete"):
        check(f"source actual read+CLIs+preview: {case}", lambda c=case: test_real_source_read_failure_consumers(c))
    for case in ("null total timing", "oversized timing total_ms", "oversized timing compilation_ms", "oversized timing evaluation_ms", "unexplained undetermined eligible", "unexplained undetermined not_eligible", "blocking override positive", "optional timing null positive"):
        check(f"timing and decision HTTP+CLIs: {case}", lambda c=case: test_identity_consumers_actual_http(c))
    for extra in (0, 50):
        check(f"source real HTTPResponse remaining={extra}", lambda v=extra: test_real_http_source_length_contract(v))
    check("artifact: valid invocation variance, invalid stored required fields", test_artifact_invocation_variance_is_validated_before_comparison)
    check("context: observed prefix/suffix and exact quote", test_quote_context_is_observed_not_just_link_construction)
    check("cache: unavailable explain/source remain single attempts", test_unavailable_explain_reuses_single_paired_source_cache)
    check("endpoint: programming NameError remains visible", test_endpoint_code_error_remains_visible)
    check("preview: expected remote failure and actual candidate contract", test_remote_candidate_expected_failures_and_contract)
    for case in ('positive', 'decide', 'explain', 'HTTP error', 'stored artifact', 'local preview', 'default preview', 'remote preview', 'nesting', 'nested invalid observation', 'reader code error'):
        check(f"JSON decoder consumers: {case}", lambda c=case: test_json_decoder_boundary_consumers(c))
    for case in ('positive', 'space', 'tab', 'leading zeros', 'short body', 'huge', 'non ASCII', 'malformed', 'negative', 'empty', 'no header', 'lower cap', 'excess body'):
        check(f"source length header consumers: {case}", lambda c=case: test_source_length_header_consumers(c))
    for case in ('complete', 'complete padded', 'short padded', 'short ordinary', 'finite read'):
        check(f"JSON complete HTTP consumers: {case}", lambda c=case: test_complete_json_http_consumers(c))
    for case in ('positive', 'extra field', 'retained response', 'live response', 'node bound'):
        check(f"whole artifact bounds: {case}", lambda c=case: test_whole_artifact_bounds(c))
    for case in ('normal', 'depth aggregation', 'node aggregation'):
        check(f"assembled artifact bounds: {case}", lambda c=case: test_assembled_artifact_bounds(c))
    check("offline: swallowed network attempt still fails suite", test_network_guard_detects_swallowed_attempt)

    width = max(len(name) for name, _, _ in _results)
    passed = 0
    for name, ok, detail in _results:
        passed += 1 if ok else 0
        print(f"  {'ok  ' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    print(f"\n{passed}/{len(_results)} provenance self-test cases passed")
    return 0 if passed == len(_results) else 1


def main() -> int:
    with deny_network():
        return _run_checks()


if __name__ == "__main__":
    raise SystemExit(main())
