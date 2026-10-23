"""Fixture-driven self-test for the live provenance probe.

The probe's value is entirely in what it *rejects*, and a probe nobody has
watched go red is not evidence of anything. This drives it against a
synthetic engine response and then, one at a time, breaks each property it
claims to enforce, asserting the matching failure appears. It needs no engine,
no credential and no network, so it runs in CI on every change.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "provenance"))

from lib.manifest import Reference, ShowcaseManifest, SourceDocument  # noqa: E402
from lib.quote_match import Quote, build_deep_link  # noqa: E402
from lib.target_safety import TargetSafetyError  # noqa: E402

DOC_BYTES = (
    b"# Synthetic Authority Act\n\n"
    b"### Section 1: Widget eligibility\n\n"
    b"(1) An applicant must hold a valid widget licence.\n\n"
    b"### Section 2: Age\n\n"
    b"(2) The applicant must be aged 18 or over at the date of application.\n"
)
DOC_URL = "https://example.test/authority/act.md"
DOC_DIGEST = "sha256:" + hashlib.sha256(DOC_BYTES).hexdigest()

QUOTE_A = Quote(exact="An applicant must hold a valid widget licence.")
QUOTE_B = Quote(exact="The applicant must be aged 18 or over at the date of application.")


class _FakeSource:
    def __init__(self) -> None:
        self.url = DOC_URL
        self.content = DOC_BYTES
        self.media_type = "text"

    @property
    def digest(self) -> str:
        return DOC_DIGEST


def _fetcher(url: str):
    if url != DOC_URL:
        raise TargetSafetyError("fetch_failure", f"unexpected fetch of {url!r}")
    return _FakeSource()


def _reference(source_id: str, quote: Quote) -> dict:
    locator = "Section 2(2)" if source_id == "ACT#S2" else "Section 1(1)"
    return {
        "schema_version": 1,
        "source_id": source_id,
        "title": "Synthetic Authority Act",
        "authority": "Synthetic Authority",
        "url": DOC_URL,
        "locator": locator,
        "source_version": "2026",
        "source_date": "2026-01-01",
        "content_digest": DOC_DIGEST,
        "licence": "MIT",
        "verified_at": "2026-07-26T00:00:00Z",
        "quote": quote.as_wire(),
        "media_type": "text",
        "deep_link": build_deep_link(DOC_URL, quote, "text", locator),
    }


def _payload() -> dict:
    return {
        "ruleset_id": "synthetic:20260726-aaaa",
        "slug": "aethis/synthetic",
        "ruleset_version": "v1",
        "content_digest": "sha256:" + "a" * 64,
        "criteria": [
            {
                "criterion_id": "widget_licence",
                "group": "licence",
                "title": "Holds a widget licence",
                "rule_text": "Holds a widget licence",
                "source_refs": ["ACT#S1"],
                "source_references": [_reference("ACT#S1", QUOTE_A)],
            },
            {
                "criterion_id": "age_18",
                "group": "age",
                "title": "Aged 18 or over",
                "rule_text": "Aged 18 or over",
                "source_refs": ["ACT#S2"],
                "source_references": [_reference("ACT#S2", QUOTE_B)],
            },
        ],
    }


def _decide_payload(explain: Optional[dict] = None) -> dict:
    """The /decide shape: the same references, nested under evaluation groups.

    The probe has to read both shapes, so the self-test must serve both. An
    earlier version of this fixture returned the /explain shape on both paths,
    which is exactly how the probe shipped unable to read a real /decide
    response while its own tests stayed green.
    """
    explain = explain or _payload()
    return {
        "decision_id": "dec_synthetic0000000",
        "inputs_hash": "sha256:" + hashlib.sha256(b"{}").hexdigest(),
        "decision_time": "2026-09-13T12:00:00Z",
        "engine_version": "aethis-core@0.60.0",
        "fields_evaluated": len(explain["criteria"]),
        "fields_provided": 0,
        "content_identity": explain["content_digest"],
        "decision": "undetermined",
        "ruleset_id": explain["ruleset_id"],
        "slug": explain["slug"],
        "ruleset_version": explain["ruleset_version"],
        "content_digest": explain["content_digest"],
        "explanation": {
            "decision": "pending",
            "unused_facts": [],
            "groups": [
                {
                    "group": criterion["group"],
                    "status": "pending",
                    "criteria": [
                        {
                            "criterion_id": criterion["criterion_id"],
                            "title": criterion["title"],
                            "status": "pending",
                            "source_refs": criterion["source_refs"],
                            "source_references": criterion["source_references"],
                        }
                    ],
                }
                for criterion in explain["criteria"]
            ],
        },
    }


def _decide_criteria(decide: dict) -> list:
    """Flat view of the nested decide criteria, for mutation in the cases."""
    return [c for group in decide["explanation"]["groups"] for c in group["criteria"]]


def _manifest(tmp: Path) -> ShowcaseManifest:
    fixture = tmp / "synthetic.explain.json"
    fixture.write_text(json.dumps(_payload(), indent=2))
    document = SourceDocument(
        doc_id="act",
        url=DOC_URL,
        title="Synthetic Authority Act",
        authority="Synthetic Authority",
        licence="MIT",
        media_type="text",
        expected_digest=DOC_DIGEST,
        source_version="2026",
        source_date="2026-01-01",
    )
    return ShowcaseManifest(
        name="synthetic",
        example_dir="synthetic",
        ruleset_slug="aethis/synthetic",
        surface="self-test",
        manifest_path=tmp / "references.yaml",
        explain_fixture=fixture,
        documents={"act": document},
        references={
            "ACT#S1": Reference(key="ACT#S1", document="act", quote=QUOTE_A, locator="Section 1(1)"),
            "ACT#S2": Reference(key="ACT#S2", document="act", quote=QUOTE_B, locator="Section 2(2)"),
        },
        criteria={"widget_licence": ["ACT#S1"], "age_18": ["ACT#S2"]},
    )


def _transport_for(explain: dict, decide: dict, *, explain_status: int = 200, decide_status: int = 200):
    def transport(url: str, *, method: str = "GET", body: Optional[dict] = None):
        if method == "POST":
            return decide_status, decide
        return explain_status, explain

    return transport


def _run(manifest: ShowcaseManifest, explain: dict, decide: dict, **kw) -> List[dict]:
    from probe_staging import probe_showcase

    row = probe_showcase(
        manifest,
        base_url="https://staging.example.test",
        fetcher=_fetcher,
        transport=_transport_for(explain, decide, **kw),
    )
    return row["failures"]


def _run_self_test() -> int:
    results: List[tuple[str, bool, str]] = []

    def case(name: str, expected_code: Optional[str], mutate=None, **kw) -> None:
        explain = _payload()
        decide = _decide_payload()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            manifest = _manifest(tmp)
            if mutate is not None:
                mutate(explain, decide)
            failures = _run(manifest, explain, decide, **kw)
        codes = {f["reason_code"] for f in failures}
        if expected_code is None:
            ok = not failures
            detail = "clean" if ok else f"unexpected failures: {sorted(codes)}"
        else:
            ok = expected_code in codes
            detail = f"got {sorted(codes) or ['<none>']}"
        results.append((name, ok, detail))

    case("well-formed response passes", None)

    def hidden_nested(explain, decide):
        decide["criteria"] = copy.deepcopy(explain["criteria"])
        _decide_criteria(decide)[0]["source_references"][0]["authority"] = "Fabricated"
    case("flat criteria cannot hide actual nested decision", "missing_criteria", hidden_nested)

    with tempfile.TemporaryDirectory() as tmpdir:
        from probe_staging import probe_showcase
        decide = _decide_payload()
        _decide_criteria(decide)[0]["source_references"][0]["authority"] = "Fabricated"
        row = probe_showcase(_manifest(Path(tmpdir)), base_url="https://staging.example.test",
                             fetcher=_fetcher, transport=_transport_for(_payload(), decide))
        ok = row["criteria_with_served_references"] is None and row.get("served_by_path") == {"explain": 2, "decide": 1}
        results.append(("divergent decision cannot inherit explain coverage", ok, str(row["criteria_with_served_references"])))


    # A body carried by a failed HTTP read is not verified engine evidence.
    for explain_status, decide_status in ((503, 200), (200, 503), (503, 503)):
        with tempfile.TemporaryDirectory() as tmpdir:
            from probe_staging import probe_showcase
            row = probe_showcase(
                _manifest(Path(tmpdir)), base_url="https://staging.example.test", fetcher=_fetcher,
                transport=_transport_for(_payload(), _decide_payload(), explain_status=explain_status, decide_status=decide_status),
            )
            ok = row["criteria_with_served_references"] is None
            if explain_status != 200:
                ok = ok and row["criteria_total"] is None
            results.append((f"failed read {explain_status}/{decide_status} has unknown coverage", ok, str(row["criteria_with_served_references"])))

    def drop_references(explain, decide):
        explain["criteria"][0]["source_references"] = []
        _decide_criteria(decide)[0]["source_references"] = []

    case("criterion serving no reference is caught", "criterion_without_reference", drop_references)

    def drop_field(explain, decide):
        for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
            del criterion["source_references"][0]["licence"]

    case("reference missing a contract field is caught", "reference_missing_fields", drop_field)

    def paraphrase(explain, decide):
        for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
            ref = criterion["source_references"][0]
            ref["quote"] = {"exact": "Applicants need a widget licence."}
            ref["deep_link"] = build_deep_link(DOC_URL, Quote(exact="Applicants need a widget licence."), "text", None)

    case("paraphrased quote is caught", "quote_not_found", paraphrase)

    def wrong_digest(explain, decide):
        for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
            criterion["source_references"][0]["content_digest"] = "sha256:" + "0" * 64

    case("digest that no longer matches the target is caught", "digest_mismatch", wrong_digest)

    def unsafe_target(explain, decide):
        for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
            criterion["source_references"][0]["url"] = "http://example.test/act.md"

    case("non-HTTPS target is caught", "unsafe_scheme", unsafe_target)

    def private_target(explain, decide):
        for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
            criterion["source_references"][0]["url"] = "https://127.0.0.1/act.md"

    case("IP-literal target is caught", "ip_literal_host", private_target)

    def bad_licence(explain, decide):
        for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
            criterion["source_references"][0]["licence"] = "All rights reserved"

    case("unlicensed reproduction is caught", "unallowed_licence", bad_licence)

    def bad_deep_link(explain, decide):
        for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
            criterion["source_references"][0]["deep_link"] = DOC_URL + "#:~:text=something-else"

    case("deep link that does not locate the quote is caught", "deep_link_mismatch", bad_deep_link)

    def future_schema(explain, decide):
        for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
            criterion["source_references"][0]["schema_version"] = 99

    case("unreadable schema version is not certified", "unsupported_schema_version", future_schema)

    def diverge(explain, decide):
        _decide_criteria(decide)[0]["source_references"] = [_reference("ACT#S2", QUOTE_B)]

    case("explain and decide disagreeing is caught", "path_divergence", diverge)

    case("non-200 from /explain is caught", "explain_status", None, explain_status=503)
    case("non-200 from /decide is caught", "decide_status", None, decide_status=500)

    def missing_criterion(explain, decide):
        explain["criteria"] = explain["criteria"][:1]
        decide["explanation"]["groups"] = decide["explanation"]["groups"][:1]

    case("criterion the fixture expects but the engine omits is caught", "criterion_absent", missing_criterion)

    def unreadable_shape(explain, decide):
        decide.clear()
        decide.update({"decision": "undetermined"})

    case("decide response with no readable criteria is caught", "missing_criteria", unreadable_shape)

    for field, value in (("authority", "Fabricated authority"), ("title", "Fabricated title"), ("source_id", "NOT-MAPPED")):
        def mutate_both(explain: dict, decide: dict, f: str = field, v: str = value) -> None:
            for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
                criterion["source_references"][0][f] = v
        code = "served_reference_set_mismatch" if field == "source_id" else "served_reference_mismatch"
        case(f"consistent fabricated {field} is caught", code, mutate_both)

    for field, value in (("target_kind", "artefact"), ("artefact_project_id", "foreign-project"), ("artefact_source_id", "foreign-source")):
        def invalid_referent(explain: dict, decide: dict, f: str = field, v: str = value) -> None:
            for criterion in (explain["criteria"][0], _decide_criteria(decide)[0]):
                criterion["source_references"][0][f] = v
        case(f"v1 {field} coupling is enforced", "served_reference_mismatch", invalid_referent)

    def extra_uncited(explain: dict, decide: dict) -> None:
        explain["criteria"].append({"criterion_id": "engine_only", "source_refs": [], "source_references": []})
        decide["explanation"]["groups"].append({"criteria": [copy.deepcopy(explain["criteria"][-1])]})
    case("new uncited engine criterion is caught", "uncited_criterion", extra_uncited)

    def decide_only_extra(explain: dict, decide: dict) -> None:
        decide["explanation"]["groups"].append({"criteria": [{"criterion_id": "decide_only", "source_refs": [], "source_references": []}]})
    case("decide-only uncited criterion is caught", "uncited_criterion", decide_only_extra)

    for name, mutate, code in (
        ("null explain criterion", lambda e,d: e["criteria"].__setitem__(0, None), "missing_criteria"),
        ("null decision criterion", lambda e,d: d["explanation"]["groups"][0]["criteria"].__setitem__(0, None), "missing_criteria"),
        ("null reference", lambda e,d: e["criteria"][0].update(source_references=[None]), "malformed_reference"),
        ("null quote", lambda e,d: e["criteria"][0]["source_references"][0].update(quote=None), "malformed_reference"),
        ("unhashable licence", lambda e,d: e["criteria"][0]["source_references"][0].update(licence=[]), "malformed_reference"),
        ("untyped locator", lambda e,d: e["criteria"][0]["source_references"][0].update(locator=[]), "malformed_reference"),
        ("null groups", lambda e,d: d["explanation"].update(groups=None), "missing_criteria"),
        ("null keys", lambda e,d: e["criteria"][0].update(source_refs=None), "missing_criteria"),
    ):
        case(name, code, mutate)

    for name, mutate, code in (
        ("different resolved ID", lambda e,d: d.update(ruleset_id="other:20260913-aaaa"), "identity_divergence"),
        ("wrong response alias", lambda e,d: d.update(slug="aethis/other"), "response_identity"),
        ("different published version", lambda e,d: d.update(ruleset_version="v2"), "identity_divergence"),
        ("different content cut", lambda e,d: d.update(content_digest="sha256:" + "b" * 64), "identity_divergence"),
        ("missing decision", lambda e,d: d.pop("decision"), "invalid_decision"),
        ("null decision", lambda e,d: d.update(decision=None), "invalid_decision"),
    ):
        case(name, code, mutate)

    for name, mutate in (
        ("missing rule text", lambda e,d: e["criteria"][0].pop("rule_text")),
        ("missing layered status", lambda e,d: d["explanation"]["groups"][0]["criteria"][0].pop("status")),
        ("invalid layered status", lambda e,d: d["explanation"]["groups"][0].update(status=[])),
        ("incorrect empty inputs hash", lambda e,d: d.update(inputs_hash="sha256:" + "b" * 64)),
        ("contradictory leaf content identity", lambda e,d: d.update(content_identity="sha256:" + "b" * 64)),
    ):
        case(name, "response_contract", mutate)

    width = max(len(name) for name, _, _ in results)
    passed = 0
    for name, ok, detail in results:
        mark = "ok  " if ok else "FAIL"
        passed += 1 if ok else 0
        print(f"  {mark}  {name.ljust(width)}  {detail}")
    print(f"\n{passed}/{len(results)} probe self-test cases passed")
    return 0 if passed == len(results) else 1


def run_self_test() -> int:
    from selftest import deny_network
    with deny_network():
        return _run_self_test()


if __name__ == "__main__":
    raise SystemExit(run_self_test())
