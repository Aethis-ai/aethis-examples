"""Offline controls for runner quota, error, and recursive-manifest behavior."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import run_tests
import test_all
from input_identity import canonical_input_hash
from scenario_manifest import build_manifest, manifest_fingerprint


class FakeResponse:
    def __init__(
        self, status: int, body: dict | None = None, retry_after: str = "0"
    ) -> None:
        self.status_code = status
        self._body = body or {}
        self.headers = {"Retry-After": retry_after}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise run_tests.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._body


class RunnerControlsTest(unittest.TestCase):
    test: ClassVar[dict] = {"inputs": {"x": True}, "expect": {"outcome": "eligible"}}

    def test_decimal_identity_uses_matching_schema_without_coercing_integer_fields(
        self,
    ) -> None:
        test = {"inputs": {"x": 0.1 + 0.2}, "expect": {"outcome": "eligible"}}
        result = {
            "decision": "eligible",
            "ruleset_id": "pin",
            "ruleset_version": "v1",
            "content_digest": "sha256:content",
            "inputs_hash": canonical_input_hash({"x": 0.3}),
        }
        schema = {
            k: result[k] for k in ("ruleset_id", "ruleset_version", "content_digest")
        }
        schema["fields"] = [{"field_id": "x", "field_type": "real"}]
        for kind in ("real", "integer", "wrong-pin"):
            candidate = copy.deepcopy(schema)
            if kind == "wrong-pin":
                candidate["content_digest"] = "sha256:other"
            else:
                candidate["fields"][0]["field_type"] = kind
            with (
                patch.object(
                    run_tests.requests,
                    "post",
                    return_value=FakeResponse(200, copy.deepcopy(result)),
                ),
                patch.object(
                    run_tests.requests, "get", return_value=FakeResponse(200, candidate)
                ),
            ):
                checked = run_tests.run_test("https://example.test", "pin", test)
            self.assertEqual(checked["passed"], kind == "real", kind)

    def test_anonymous_requests_are_lean(self) -> None:
        response = FakeResponse(
            200,
            {
                "decision": "eligible",
                "ruleset_id": "pin",
                "inputs_hash": canonical_input_hash({"x": True}),
            },
        )
        with patch.object(run_tests.requests, "post", return_value=response) as post:
            result = run_tests.run_test("https://example.test", "pin", self.test)
        self.assertTrue(result["passed"])
        payload = post.call_args.kwargs["json"]
        self.assertFalse(payload["include_explanation"])
        self.assertFalse(payload["include_trace"])
        self.assertFalse(payload["include_timing"])

    def test_retries_a_rate_limit_then_succeeds(self) -> None:
        responses = [
            FakeResponse(429, retry_after="0"),
            FakeResponse(
                200,
                {
                    "decision": "eligible",
                    "ruleset_id": "pin",
                    "inputs_hash": canonical_input_hash({"x": True}),
                },
            ),
        ]
        with (
            patch.object(run_tests.requests, "post", side_effect=responses),
            patch.object(run_tests.time, "sleep") as sleep,
        ):
            result = run_tests.run_test("https://example.test", "pin", self.test)
        self.assertTrue(result["passed"])
        sleep.assert_called_once_with(0.0)

    def test_retry_exhaustion_fails_loudly(self) -> None:
        with (
            patch.object(
                run_tests.requests,
                "post",
                return_value=FakeResponse(429, retry_after="0"),
            ),
            patch.object(run_tests.time, "sleep"),
        ):
            result = run_tests.run_test(
                "https://example.test", "pin", self.test, max_retries=1
            )
        self.assertFalse(result["passed"])
        self.assertIn("rate limited", result["error"])

    def test_blocking_field_errors_fail_even_if_outcome_matches(self) -> None:
        response = FakeResponse(
            200,
            {
                "decision": "eligible",
                "ruleset_id": "pin",
                "inputs_hash": canonical_input_hash({"x": True}),
                "field_errors": {"x": "invalid"},
            },
        )
        with patch.object(run_tests.requests, "post", return_value=response):
            result = run_tests.run_test("https://example.test", "pin", self.test)
        self.assertFalse(result["passed"])
        self.assertIn("blocking field_errors", result["error"])

    def test_input_identity_must_match_sent_fields(self) -> None:
        for returned in (None, canonical_input_hash({"x": False})):
            response = FakeResponse(
                200,
                {"decision": "eligible", "ruleset_id": "pin", "inputs_hash": returned},
            )
            with patch.object(run_tests.requests, "post", return_value=response):
                result = run_tests.run_test("https://example.test", "pin", self.test)
            self.assertFalse(result["passed"])
            self.assertIn("input identity", result["error"])

    def test_response_identity_must_match_requested_pin(self) -> None:
        for returned in (None, "different-artifact"):
            with patch.object(
                run_tests.requests,
                "post",
                return_value=FakeResponse(
                    200, {"decision": "eligible", "ruleset_id": returned}
                ),
            ):
                self.assertFalse(
                    run_tests.run_test("https://example.test", "pin", self.test)[
                        "passed"
                    ]
                )

    def test_field_error_cannot_override_expected_outcome(self) -> None:
        response = FakeResponse(
            200,
            {
                "decision": "undetermined",
                "ruleset_id": "pin",
                "inputs_hash": canonical_input_hash({"x": "bad"}),
                "field_errors": {"x": "invalid"},
            },
        )
        for outcome, passed in (
            ("eligible", False),
            ("not_eligible", False),
            ("undetermined", True),
        ):
            test = {
                "inputs": {"x": "bad"},
                "expect": {"outcome": outcome, "field_error": "invalid"},
            }
            with patch.object(run_tests.requests, "post", return_value=response):
                self.assertEqual(
                    run_tests.run_test("https://example.test", "pin", test)["passed"],
                    passed,
                )

    def test_reviewed_fingerprint_rejects_changed_expectations_pins_and_identity(
        self,
    ) -> None:
        manifest = build_manifest()
        self.assertEqual(
            manifest_fingerprint(manifest), test_all.REVIEWED_MANIFEST_SHA256
        )
        examples = test_all.discover_examples()
        test_all.verify_manifest(examples, manifest)
        for field, value in (
            ("live_ruleset_id", "different-pin"),
            ("name", "replacement"),
            ("expectation", {"outcome": "eligible", "field_error": "invalid"}),
        ):
            changed = copy.deepcopy(manifest)
            changed["scenarios"][0][field] = value
            with self.assertRaises(SystemExit):
                test_all.verify_manifest(examples, changed)

    def test_missing_and_malformed_scenarios_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(SystemExit):
                run_tests.load_tests(root)
            (root / "tests").mkdir()
            for text in (
                "tests: []",
                "tests: null",
                "tests: [null]",
                "tests: [{name: bad, inputs: {}, expect: {outcome: nonsense}}]",
            ):
                (root / "tests/scenarios.yaml").write_text(text)
                with self.assertRaises((ValueError, TypeError)):
                    run_tests.load_tests(root)

    def test_manifest_has_all_nested_cases_and_inputs(self) -> None:
        manifest = build_manifest()
        self.assertEqual(manifest["expected_count"], 56)
        self.assertEqual(len(manifest["scenarios"]), 56)
        self.assertTrue(all(entry["field_values"] for entry in manifest["scenarios"]))
        nested = [
            entry
            for entry in manifest["scenarios"]
            if "uk-free-school-meals/sections/" in entry["test_file"]
        ]
        self.assertEqual(len(nested), 23)
        self.assertFalse(
            any(
                entry["test_file"].startswith("_template/")
                for entry in manifest["scenarios"]
            )
        )

    def test_aggregate_runner_refuses_incomplete_child_summary(self) -> None:
        complete = {
            "expected": 5,
            "executed": 5,
            "passed": 5,
            "failed": 0,
            "skipped": 0,
            "ruleset_id": "immutable-pin",
        }
        self.assertEqual(
            test_all.complete_suite_summary(complete, 5, "immutable-pin"),
            {key: complete[key] for key in test_all.SUMMARY_COUNTS},
        )
        for incomplete in (
            {**complete, "executed": 1, "passed": 1, "failed": 4},
            {**complete, "skipped": 1, "passed": 4},
            {key: value for key, value in complete.items() if key != "failed"},
            {**complete, "ruleset_id": "different-pin"},
        ):
            with self.assertRaises(ValueError):
                test_all.complete_suite_summary(incomplete, 5, "immutable-pin")


if __name__ == "__main__":
    unittest.main()
