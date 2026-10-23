"""Offline check: every spacecraft engine input carries a canonical field name.

The rulebook's field vocabulary (spacecraft-crew-certification/rulebook.yaml)
pairs each input of the pinned member ruleset with a `canonical_field`. This
test compares it against the compiled fields recorded in the pinned snapshot,
so a regenerated ruleset that adds, drops or retypes a field fails here before
the vocabulary is applied to an engine.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

EXAMPLE = Path(__file__).resolve().parent.parent / "spacecraft-crew-certification"
CANONICAL_NAME = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
SUBJECTS = {"crew_member", "mission", "vessel"}
SNAPSHOT = EXAMPLE / "snapshots" / "spacecraft-crew-certification.json"
# snapshots/ is a raw database export and is never published, so the tests that
# read it can only run in the internal repository.
needs_snapshot = unittest.skipUnless(
    SNAPSHOT.exists(), "snapshots/ is not published; these tests run in the internal repository"
)


def _vocabulary() -> list[dict]:
    doc = yaml.safe_load((EXAMPLE / "rulebook.yaml").read_text())
    return doc["rulebook"]["fields"]


def _pinned_compiled_fields() -> dict[str, str]:
    pinned = yaml.safe_load((EXAMPLE / "aethis.yaml").read_text())["live_ruleset_id"]
    snapshot = json.loads(
        (EXAMPLE / "snapshots" / "spacecraft-crew-certification.json").read_text()
    )
    bundles = [
        b
        for b in snapshot["collections"]["rule_bundles_dsl"]
        if b.get("bundle_id") == pinned
    ]
    if len(bundles) != 1:
        raise AssertionError(
            f"snapshot holds {len(bundles)} bundles for pinned ruleset {pinned!r}"
        )
    return {f["key"]: f["sort"] for f in bundles[0]["compiled_fields"]}


class SpacecraftVocabularyTest(unittest.TestCase):
    def test_release_resources_preserve_every_existing_pairing_and_type(self) -> None:
        resources = EXAMPLE / "resources"
        canonical = yaml.safe_load((resources / "applicant_vocabulary.yaml").read_text())
        groups = yaml.safe_load((resources / "field_vocabulary.yaml").read_text())
        fields = {key: value for group in groups.values() for key, value in group.items()}
        declared = _vocabulary()
        self.assertEqual(set(canonical), {f["canonical_field"] for f in declared})
        self.assertEqual(set(fields), {f["key"] for f in declared})
        for f in declared:
            with self.subTest(key=f["key"]):
                self.assertEqual(fields[f["key"]], {"from": f["canonical_field"]})
                self.assertEqual(canonical[f["canonical_field"]]["type"], f["sort"].upper())

    def test_crew_record_recovers_only_the_printed_age(self) -> None:
        registry = yaml.safe_load((EXAMPLE / "resources" / "document_registry.yaml").read_text())
        record = registry["document_types"]["crew_record"]
        self.assertEqual(record["subject"], "applicant")
        self.assertEqual(record["collection"], [{"mode": "upload", "verification": "caseworker_review"}])
        self.assertNotIn("implied_facts", record)
        edges = record["recoverable_from"]
        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual(edge["field"], "crew_member.age")
        self.assertEqual(edge["source_fields"], ["crew_age"])
        self.assertEqual(edge["marker"], "verbatim")
        pattern = re.compile(edge["value_pattern"])
        for value in ("0", "24", "25"):
            self.assertIsNotNone(pattern.fullmatch(value))
        for value in ("twenty four", "24.5", "24 years", "", "-1"):
            self.assertIsNone(pattern.fullmatch(value))

    @needs_snapshot
    def test_every_compiled_field_has_exactly_one_vocabulary_entry(self) -> None:
        compiled = _pinned_compiled_fields()
        keys = [f["key"] for f in _vocabulary()]
        self.assertEqual(len(compiled), 11)
        self.assertEqual(len(keys), len(set(keys)), "duplicate vocabulary keys")
        self.assertEqual(set(keys), set(compiled))

    @needs_snapshot
    def test_vocabulary_sort_matches_compiled_sort(self) -> None:
        compiled = _pinned_compiled_fields()
        for f in _vocabulary():
            with self.subTest(key=f["key"]):
                self.assertEqual(f["sort"], compiled[f["key"]])

    def test_snapshot_tests_are_not_skipped_when_the_snapshot_exists(self) -> None:
        """The skip must only ever fire for a tree that has no snapshots/."""
        if not SNAPSHOT.exists():
            self.skipTest("no snapshots/ in this tree (published mirror)")
        for name in (
            "test_every_compiled_field_has_exactly_one_vocabulary_entry",
            "test_vocabulary_sort_matches_compiled_sort",
        ):
            with self.subTest(test=name):
                self.assertFalse(getattr(getattr(type(self), name), "__unittest_skip__", False))

    def test_every_field_declares_a_well_formed_unique_canonical_field(self) -> None:
        names = []
        for f in _vocabulary():
            with self.subTest(key=f["key"]):
                name = f.get("canonical_field")
                self.assertIsInstance(name, str)
                self.assertRegex(name, CANONICAL_NAME)
                self.assertIn(name.split(".", 1)[0], SUBJECTS)
                names.append(name)
        self.assertEqual(len(names), len(set(names)), "duplicate canonical_field")


if __name__ == "__main__":
    unittest.main()
