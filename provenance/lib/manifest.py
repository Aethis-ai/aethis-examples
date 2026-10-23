"""Load and structurally validate the launch-showcase provenance manifests.

Two files describe the provenance of the public showcases:

``provenance/showcase.yaml``
    The launch-showcase registry: which published rulesets the public surface
    puts in front of a visitor, and where each one's citation manifest lives.
    This is the denominator. It is a registry of *rulesets*, never of
    criteria - a showcase cannot shrink its own denominator.

``<example>/sources/references.yaml``
    One per showcase. Declares the cited documents, the citation keys that
    resolve against them, and the criterion-to-citation-key mapping. Its
    ``documents`` entries are exactly the resolution targets the publish call
    sends, so the manifest is the single source for both the local gate and
    the publish payload.

Everything here is structural: shape, required fields, dangling references,
licence allowlist. Network verification (fetch, digest, quote occurrence)
lives in ``check_provenance.py`` so the structural half stays runnable
offline.
"""

from __future__ import annotations

import json
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .quote_match import MEDIA_HTML, MEDIA_PDF, MEDIA_TEXT, Quote

SCHEMA_VERSION = 1

# Licences under which we are willing to reproduce a quoted passage in a
# public repository. An unlisted licence fails closed: "I could not find a
# licence" must never resolve to "publish it anyway".
ALLOWED_LICENCES = {
    "MIT",
    "OGL-UK-3.0",
    "CC-BY-4.0",
    "CC0-1.0",
    "Crown-Copyright-OGL-UK-3.0",
}

VALID_MEDIA_TYPES = {MEDIA_HTML, MEDIA_PDF, MEDIA_TEXT}

# Subject matter the public demonstration corpus does not cover.
#
# The phrase list lives in `scripts/restricted-phrases.txt`, which publish.sh
# excludes from the public mirror - the gate travels, the list does not. A
# denylist shipped next to the corpus it protects tells every reader what we
# thought worth excluding, which is a hint about what we build.
#
# Missing list means the check cannot run, and a check that cannot run must not
# report success: it raises rather than passing quietly. The authoritative run
# is therefore the internal one, which is also the only place that gates a
# merge.
RESTRICTED_PHRASES_PATH = Path(__file__).resolve().parents[2] / "scripts" / "restricted-phrases.txt"


class RestrictedBoundaryUnavailable(RuntimeError):
    """The phrase list is absent, so the boundary cannot be enforced."""


@lru_cache(maxsize=1)
def load_restricted_phrases(path: Optional[Path] = None) -> tuple:
    """Lower-cased restricted phrases. Substring match, so a stem covers its
    inflections."""
    source = path or RESTRICTED_PHRASES_PATH
    if not source.is_file():
        raise RestrictedBoundaryUnavailable(
            f"restricted-phrase list not found at {source}. The boundary check cannot run, and a "
            "check that cannot run must not report success. This list is internal-only: run the "
            "gate from the source repository, not the published mirror."
        )
    return tuple(
        line.strip().lower()
        for line in source.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def find_restricted_phrase(text: str, phrases: Optional[tuple] = None) -> Optional[str]:
    """The first restricted phrase occurring in ``text``, or None.

    Returns the phrase so the caller can name it. An error that says "this is
    not allowed" without saying which words tripped it just makes the author
    guess.
    """
    lowered = text.lower()
    for phrase in phrases if phrases is not None else load_restricted_phrases():
        if phrase in lowered:
            return phrase
    return None


class ManifestError(ValueError):
    """A manifest is structurally invalid. Fails the gate closed."""


@dataclass(frozen=True)
class SourceDocument:
    """One cited document: the resolution target sent at publish time."""

    doc_id: str
    url: str
    title: str
    authority: str
    licence: str
    media_type: str
    source_version: Optional[str] = None
    source_date: Optional[str] = None
    expected_digest: Optional[str] = None
    local_path: Optional[str] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class Reference:
    """One citation key bound to a document and a verbatim passage."""

    key: str
    document: str
    quote: Quote
    locator: Optional[str] = None


@dataclass
class ShowcaseManifest:
    """A showcase's citations plus its criterion mapping."""

    name: str
    example_dir: str
    ruleset_slug: str
    surface: str
    manifest_path: Path
    explain_fixture: Path
    documents: Dict[str, SourceDocument]
    references: Dict[str, Reference]
    criteria: Dict[str, List[str]]
    claim_blocked_by: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def fixture_criteria(self) -> List[str]:
        """Criterion ids recorded in the committed explanation snapshot.

        This is a *cache*, not the denominator. It exists so the gate can run
        without a network, and so drift against the engine can be detected by
        diffing. Anything that decides coverage must use the live criteria
        instead: a committed file is editable, and a denominator that can be
        edited is not a guarantee.
        """
        data = json.loads(self.explain_fixture.read_text())
        return [c["criterion_id"] for c in data.get("criteria", [])]

    def fixture_declared_keys(self) -> Dict[str, List[str]]:
        """criterion_id -> citation keys recorded in the snapshot. Same caveat."""
        data = json.loads(self.explain_fixture.read_text())
        return {c["criterion_id"]: list(c.get("source_refs") or []) for c in data.get("criteria", [])}


def _require(mapping: dict, key: str, where: str) -> object:
    if key not in mapping or mapping[key] in (None, ""):
        raise ManifestError(f"{where}: missing required field {key!r}")
    return mapping[key]


def _scan_forbidden(text: str, where: str, phrases: Optional[tuple] = None) -> None:
    hit = find_restricted_phrase(text, phrases)
    if hit:
        raise ManifestError(
            f"{where}: quotes restricted subject matter ({hit!r}). This corpus is deliberately "
            "synthetic, or openly licensed and impersonal; cite a source that meets that bar "
            "rather than widening the boundary."
        )


def load_showcase_manifest(root: Path, entry: dict) -> ShowcaseManifest:
    """Load one showcase's ``references.yaml`` and bind it to the registry entry."""
    name = str(_require(entry, "name", "showcase entry"))
    example_dir = str(_require(entry, "example_dir", f"showcase {name}"))
    manifest_path = root / str(_require(entry, "references", f"showcase {name}"))
    explain_fixture = root / str(_require(entry, "explain_fixture", f"showcase {name}"))

    if not manifest_path.is_file():
        raise ManifestError(f"showcase {name}: references manifest not found at {manifest_path}")
    if not explain_fixture.is_file():
        raise ManifestError(f"showcase {name}: explanation fixture not found at {explain_fixture}")

    raw = yaml.safe_load(manifest_path.read_text()) or {}
    where = f"{manifest_path}"
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"{where}: schema_version must be {SCHEMA_VERSION}")

    documents: Dict[str, SourceDocument] = {}
    for doc_id, doc in (raw.get("documents") or {}).items():
        dwhere = f"{where}: documents.{doc_id}"
        licence = str(_require(doc, "licence", dwhere))
        if licence not in ALLOWED_LICENCES:
            raise ManifestError(
                f"{dwhere}: licence {licence!r} is not on the allowlist "
                f"({', '.join(sorted(ALLOWED_LICENCES))}). Reproducing a passage "
                "under an unverified licence fails closed."
            )
        media_type = str(doc.get("media_type") or MEDIA_TEXT)
        if media_type not in VALID_MEDIA_TYPES:
            raise ManifestError(f"{dwhere}: media_type must be one of {sorted(VALID_MEDIA_TYPES)}")
        digest = doc.get("expected_digest")
        if digest is not None and not (
            isinstance(digest, str) and digest.startswith("sha256:") and len(digest) == 71
        ):
            raise ManifestError(f"{dwhere}: expected_digest must look like 'sha256:<64 hex chars>'")
        documents[doc_id] = SourceDocument(
            doc_id=doc_id,
            url=str(_require(doc, "url", dwhere)),
            title=str(_require(doc, "title", dwhere)),
            authority=str(_require(doc, "authority", dwhere)),
            licence=licence,
            media_type=media_type,
            source_version=doc.get("source_version"),
            source_date=doc.get("source_date"),
            expected_digest=digest,
            local_path=doc.get("local_path"),
            note=doc.get("note"),
        )
    if not documents:
        raise ManifestError(f"{where}: at least one cited document is required")

    references: Dict[str, Reference] = {}
    for key, ref in (raw.get("references") or {}).items():
        rwhere = f"{where}: references[{key!r}]"
        doc_id = str(_require(ref, "document", rwhere))
        if doc_id not in documents:
            raise ManifestError(f"{rwhere}: document {doc_id!r} is not declared")
        quote_raw = ref.get("quote") or {}
        exact = str(_require(quote_raw, "exact", f"{rwhere}.quote"))
        _scan_forbidden(exact, rwhere)
        references[key] = Reference(
            key=key,
            document=doc_id,
            quote=Quote(
                exact=exact,
                prefix=quote_raw.get("prefix"),
                suffix=quote_raw.get("suffix"),
            ),
            locator=ref.get("locator"),
        )
    if not references:
        raise ManifestError(f"{where}: at least one reference is required")

    criteria: Dict[str, List[str]] = {}
    for criterion_id, keys in (raw.get("criteria") or {}).items():
        cwhere = f"{where}: criteria.{criterion_id}"
        if not isinstance(keys, list) or not keys:
            raise ManifestError(f"{cwhere}: must list at least one citation key")
        for key in keys:
            if key not in references:
                raise ManifestError(f"{cwhere}: citation key {key!r} is not declared under references")
        criteria[criterion_id] = [str(k) for k in keys]

    return ShowcaseManifest(
        name=name,
        example_dir=example_dir,
        ruleset_slug=str(_require(entry, "ruleset_slug", f"showcase {name}")),
        surface=str(entry.get("surface") or "unspecified"),
        manifest_path=manifest_path,
        explain_fixture=explain_fixture,
        documents=documents,
        references=references,
        criteria=criteria,
        claim_blocked_by=entry.get("claim_blocked_by"),
        notes=list(raw.get("notes") or []),
    )


def scan_corpus_documents(manifests: List["ShowcaseManifest"], root: Path) -> List[dict]:
    """Scan the cited corpus FILES, not just the quoted passages.

    The quote scanner only ever saw the text a manifest chose to quote, which
    is a small fraction of each document. A restricted phrase sitting in a part
    of the corpus nobody quoted was invisible to it - and one was: a modelling
    note in a source document, on the published mirror, naming two real
    instruments. Scanning the whole file is the check that would have caught
    it, so it is the check that runs now.

    Returns findings rather than raising: the caller decides whether a hit
    blocks, and an exempted hit still has to be listed somewhere a human reads.
    """
    findings: List[dict] = []
    seen: set = set()
    phrases = load_restricted_phrases()
    for manifest in manifests:
        for doc in manifest.documents.values():
            if not doc.local_path or doc.local_path in seen:
                continue
            seen.add(doc.local_path)
            path = root / doc.local_path
            if not path.is_file():
                continue
            for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
                hit = find_restricted_phrase(line, phrases)
                if hit:
                    findings.append(
                        {
                            "showcase": manifest.name,
                            "document": doc.doc_id,
                            "path": doc.local_path,
                            "line": lineno,
                            "phrase": hit,
                        }
                    )
    return findings


def load_registry(root: Path, registry_path: Optional[Path] = None) -> List[ShowcaseManifest]:
    """Load every showcase declared in ``provenance/showcase.yaml``."""
    path = registry_path or (root / "provenance" / "showcase.yaml")
    if not path.is_file():
        raise ManifestError(f"launch-showcase registry not found at {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(f"{path}: schema_version must be {SCHEMA_VERSION}")
    entries = raw.get("showcases") or []
    if not entries:
        raise ManifestError(f"{path}: the registry declares no showcases")
    manifests = [load_showcase_manifest(root, entry) for entry in entries]

    # The registry is hand-maintained against the public gallery, so deleting an
    # entry would quietly shrink the total that everything else is measured
    # against - the same failure the criterion denominator is protected from,
    # one level up. The lock file is the independent record: every slug in it
    # must still be present.
    lock_path = path.parent / "showcase.lock"
    if not lock_path.is_file():
        # An anti-tamper file whose bypass is deleting the anti-tamper file is
        # not anti-tamper. Absent means the guarantee is gone, so the load
        # fails rather than quietly reverting to trusting the registry.
        raise ManifestError(
            f"{lock_path} is missing. It is the independent record of which rulesets carry the "
            "public claim; without it a showcase can be dropped from the registry unnoticed. "
            "Restore it, or update it deliberately in the same change that removes a showcase."
        )
    if True:
        locked = [
            line.strip()
            for line in lock_path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        present = {m.ruleset_slug for m in manifests}
        missing = [slug for slug in locked if slug not in present]
        if missing:
            raise ManifestError(
                f"{path}: showcase(s) {missing} are recorded in {lock_path.name} but no longer "
                "declared in the registry. Removing a ruleset from the launch surface is a "
                "deliberate act: update the lock in the same change, and make sure the public "
                "copy stops claiming it."
            )
    return manifests
