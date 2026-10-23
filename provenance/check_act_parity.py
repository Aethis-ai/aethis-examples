#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Check the canonical spacecraft Act against the frozen published benchmark copy.

Two copies of the Spacecraft Crew Certification Act matter:

* ``spacecraft-crew-certification/sources/source.md`` - the canonical Act, which
  the showcase ruleset is authored from and which people edit;
* the dataset copy published with the benchmark - frozen, because published
  results were measured against it.

The benchmark copy carries answer-key annotations the canonical Act does not,
but its **normative text** (``### Section 1`` up to the first ``## Appendix``)
must say the same thing, clause for clause. A change to the canonical Act that
alters what a clause says is exactly the drift this catches: it is how the Act
once came to contradict itself without anyone noticing.

What the check does:

1. fetches the benchmark copy at the commit pinned in ``PARITY.lock``, with the
   bounded fetcher, and verifies its sha256 digest. A fetch failure fails the
   check; it is never skipped;
2. takes the normative text of both copies, drops ``---`` rule lines and
   normalises whitespace. Answer-key annotations (whole-line ``*[Pattern: ...]*``
   markers and ``>`` blockquotes) are dropped from the **benchmark copy only**.
   The canonical Act is what authoring reads, so any annotation-shaped line in
   its normative text is itself a failure - a blockquote there is text the
   authoring model sees, not a comment;
   a repeated subsection number in either copy is also a failure;
3. compares them subsection by subsection, in order, removing only the differences
   listed in ``PARITY_EXCEPTIONS.yaml``. Each exception must match its recorded
   text exactly, so it cannot silently cover some other change;
4. runs negative controls against the same fetched bytes - one changed word,
   a duplicated subsection and a blockquote added to the canonical Act, and each
   exception removed in turn - and fails unless every one is caught. A check that
   cannot go red is not checking anything.

The benchmark repository, path and digest are also fixed in this script, so the
lock file cannot be re-pointed at another copy (a fork, a later commit) without
the change showing up here too.

What it does not do: judge whether a difference is *harmless*. Any wording
change to a normative clause fails, including a pure rephrasing; resolve it by
restoring parity or, after reading both copies, recording a reviewed exception.

What it does not establish: anything outside the normative text. The preamble
before ``### Section 1`` and everything from the first ``## Appendix`` onwards
(field registries, outcome logic, coverage matrices) are not compared at all,
in either copy.

Exit 0 on parity, 1 on any difference, fetch failure or failed control.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "provenance"))

from lib.fetching import fetch_source
from lib.target_safety import TargetSafetyError

SOURCES = ROOT / "spacecraft-crew-certification" / "sources"
CANONICAL = SOURCES / "source.md"
# Kept outside ``sources/``: authoring uploads every file under ``sources/``.
PARITY = SOURCES.parent / "parity"
LOCK = PARITY / "PARITY.lock"
EXCEPTIONS = PARITY / "PARITY_EXCEPTIONS.yaml"

SIDES = ("benchmark", "canonical")

# The only copy this check may be pointed at. Kept here as well as in
# PARITY.lock so that re-pointing the lock alone fails.
EXPECTED_REPOSITORY = "Aethis-ai/confidently-wrong-benchmark"
EXPECTED_PATH = "dataset/spacecraft-crew-certification/source.md"
EXPECTED_DIGEST = (
    "sha256:8a03e85e890b47abd8616505315621af3afb1492b5a7a73e9791bb116d154fa5"
)

_SECTION_RE = re.compile(r"^### Section (\w+)\b")
_SUBSECTION_RE = re.compile(r"^\((\d+)\)")
# A whole-line answer-key marker, and nothing else on the line.
_PATTERN_RE = re.compile(r"^\*\[Pattern:[^\]]*\]\*$")
_RULE_RE = re.compile(r"^-{3,}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# Subsections of one section, in order. The label "" holds the section heading
# and anything before its first numbered subsection.
Subsections = list[tuple[str, list[str]]]
Act = dict[str, Subsections]


class ParityError(Exception):
    """The check could not be carried out (bad lock, bad exceptions, bad text)."""


@dataclass(frozen=True)
class ParityException:
    section: str
    subsection: str
    present_in: str
    text: str
    reason: str

    @property
    def ref(self) -> str:
        return f"§{self.section}({self.subsection})"


def normalise(line: str) -> str:
    return " ".join(line.split())


def normative_text(
    markdown: str, *, label: str, strip_annotations: bool
) -> tuple[Act, list[str]]:
    """Split the normative part of an Act into sections and subsections.

    Returns the sections and a list of structural problems. With
    ``strip_annotations`` (benchmark copy only) whole-line answer-key markers and
    blockquotes are dropped; without it they are reported as problems.
    """
    lines = markdown.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("### Section 1")), None
    )
    if start is None:
        raise ParityError(f"{label}: no '### Section 1' heading")
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith("## Appendix")),
        None,
    )
    if end is None:
        raise ParityError(f"{label}: no '## Appendix' heading after Section 1")

    act: Act = {}
    problems: list[str] = []
    current: Subsections = []
    number = ""
    for raw in lines[start:end]:
        line = normalise(raw)
        if not line or _RULE_RE.match(line):
            continue
        if line.startswith(">") or "*[Pattern:" in line:
            if strip_annotations and (line.startswith(">") or _PATTERN_RE.match(line)):
                continue
            if not strip_annotations:
                problems.append(
                    f"§{number}: annotation-style line in the {label} - the canonical "
                    f"Act is read by authoring, so it must carry no blockquotes or "
                    f"pattern markers\n    {line}"
                )
                continue
        heading = _SECTION_RE.match(line)
        if heading:
            number = heading.group(1)
            if number in act:
                raise ParityError(f"{label}: Section {number} appears twice")
            current = [("", [])]
            act[number] = current
            current[0][1].append(line)
            continue
        numbered = _SUBSECTION_RE.match(line)
        if numbered:
            sub = numbered.group(1)
            if any(existing == sub for existing, _ in current):
                problems.append(
                    f"§{number}({sub}): subsection number appears twice in the {label}\n    {line}"
                )
            current.append((sub, []))
        current[-1][1].append(line)
    return act, problems


def load_lock(path: Path = LOCK) -> dict[str, str]:
    lock = yaml.safe_load(path.read_text()) or {}
    for key in ("repository", "commit", "path", "digest"):
        if not isinstance(lock.get(key), str) or not lock[key]:
            raise ParityError(f"{path.name}: '{key}' is missing")
    if not _COMMIT_RE.match(lock["commit"]):
        raise ParityError(
            f"{path.name}: 'commit' must be a full 40-character sha, not a branch or tag"
        )
    if not _DIGEST_RE.match(lock["digest"]):
        raise ParityError(f"{path.name}: 'digest' must be sha256:<64 hex>")
    expected = {
        "repository": EXPECTED_REPOSITORY,
        "path": EXPECTED_PATH,
        "digest": EXPECTED_DIGEST,
    }
    for key, value in expected.items():
        if lock[key] != value:
            raise ParityError(
                f"{path.name}: '{key}' is {lock[key]!r}, but this check only accepts "
                f"{value!r}. The benchmark copy is frozen; changing it means changing "
                f"this script too, deliberately."
            )
    return lock


def load_exceptions(path: Path = EXCEPTIONS) -> list[ParityException]:
    data = yaml.safe_load(path.read_text()) or {}
    entries = data.get("exceptions") or []
    if not isinstance(entries, list):
        raise ParityError(f"{path.name}: 'exceptions' must be a list")
    out: list[ParityException] = []
    for index, entry in enumerate(entries):
        where = f"{path.name} entry {index + 1}"
        if not isinstance(entry, dict):
            raise ParityError(f"{where}: must be a mapping")
        fields = {
            key: entry.get(key)
            for key in ("section", "subsection", "present_in", "text", "reason")
        }
        for key, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ParityError(
                    f"{where}: '{key}' is required and must be a non-empty string"
                )
        if fields["present_in"] not in SIDES:
            raise ParityError(
                f"{where}: 'present_in' must be one of {', '.join(SIDES)}"
            )
        out.append(
            ParityException(
                section=fields["section"].strip(),
                subsection=fields["subsection"].strip(),
                present_in=fields["present_in"],
                text=normalise(fields["text"]),
                reason=fields["reason"].strip(),
            )
        )
    return out


def apply_exceptions(
    acts: dict[str, Act], exceptions: list[ParityException]
) -> list[str]:
    """Remove each excepted subsection from the side that carries it.

    Returns a failure for every exception that does not match its recorded text.
    """
    failures: list[str] = []
    for exc in exceptions:
        subsections = acts[exc.present_in].get(exc.section)
        match = None
        if subsections is not None:
            match = next(
                (
                    i
                    for i, (label, _lines) in enumerate(subsections)
                    if label == exc.subsection
                ),
                None,
            )
        if match is None:
            failures.append(
                f"{exc.ref}: exception is stale - no such subsection in the {exc.present_in} copy"
            )
            continue
        found = " ".join(subsections[match][1])
        if found != exc.text:
            failures.append(
                f"{exc.ref}: exception text no longer matches the {exc.present_in} copy\n"
                f"    recorded: {exc.text}\n"
                f"    found:    {found}"
            )
            continue
        del subsections[match]
    return failures


def compare(
    benchmark_md: str, canonical_md: str, exceptions: list[ParityException]
) -> list[str]:
    """Every normative difference not covered by a reviewed exception."""
    bench, bench_problems = normative_text(
        benchmark_md, label="benchmark copy", strip_annotations=True
    )
    canon, canon_problems = normative_text(
        canonical_md, label="canonical source.md", strip_annotations=False
    )
    failures = bench_problems + canon_problems
    failures += apply_exceptions({"benchmark": bench, "canonical": canon}, exceptions)

    for number in bench.keys() - canon.keys():
        failures.append(f"§{number}: section only in the benchmark copy")
    for number in canon.keys() - bench.keys():
        failures.append(f"§{number}: section only in the canonical source.md")
    if [n for n in bench if n in canon] != [n for n in canon if n in bench]:
        failures.append(
            f"sections are in a different order: benchmark {list(bench)} vs canonical {list(canon)}"
        )

    for number in (n for n in bench if n in canon):
        b_labels = [label for label, _ in bench[number]]
        c_labels = [label for label, _ in canon[number]]
        if b_labels == c_labels:
            pairs = zip(bench[number], canon[number])
        else:
            failures.append(
                f"§{number}: subsections differ in number or order: "
                f"benchmark {b_labels[1:]} vs canonical {c_labels[1:]}"
            )
            # Still name what differs, pairing each label's first occurrence.
            b, c = {}, {}
            for label, text in bench[number]:
                b.setdefault(label, text)
            for label, text in canon[number]:
                c.setdefault(label, text)
            for label in [lab for lab in b_labels if lab not in c]:
                failures.append(
                    f"§{number}({label}): only in the benchmark copy\n    "
                    + " ".join(b[label])
                )
            for label in [lab for lab in c_labels if lab not in b]:
                failures.append(
                    f"§{number}({label}): only in the canonical source.md\n    "
                    + " ".join(c[label])
                )
            pairs = (((lab, b[lab]), (lab, c[lab])) for lab in b if lab in c)
        for (label, b_text), (_, c_text) in pairs:
            if b_text != c_text:
                ref = f"§{number}" + (f"({label})" if label else " heading")
                diff = difflib.unified_diff(
                    b_text, c_text, "benchmark", "canonical", lineterm="", n=0
                )
                failures.append(f"{ref}: wording differs\n    " + "\n    ".join(diff))
    return failures


def fetch_benchmark(lock: dict[str, str]) -> str:
    url = f"https://raw.githubusercontent.com/{lock['repository']}/{lock['commit']}/{lock['path']}"
    try:
        fetched = fetch_source(url)
    except TargetSafetyError as exc:
        raise ParityError(
            f"could not fetch the benchmark copy ({exc.reason_code}): {exc}"
        ) from exc
    if fetched.digest != lock["digest"]:
        raise ParityError(
            f"benchmark copy digest {fetched.digest} does not match the pinned {lock['digest']} "
            f"(from {url}). The published copy is meant to be frozen; do not re-pin without reading it."
        )
    return fetched.content.decode("utf-8")


def _first_normative_word(canonical_md: str) -> tuple[str, str]:
    """Change one word of the first numbered subsection of Section 3 (in memory)."""
    lines = canonical_md.splitlines(keepends=True)
    in_section = False
    for i, line in enumerate(lines):
        if line.startswith("### Section 3"):
            in_section = True
        elif in_section and _SUBSECTION_RE.match(line.strip()):
            words = line.split(" ")
            for j, word in enumerate(words):
                if word.isalpha() and len(word) > 3:
                    words[j] = word + "x"
                    lines[i] = " ".join(words)
                    return "".join(lines), "§3(1)"
    raise ParityError("negative control: could not find a word to change in Section 3")


def _insert_after_section_line(canonical_md: str, section: str, new_line: str) -> str:
    """Insert ``new_line`` after the last numbered subsection line of a section."""
    lines = canonical_md.splitlines(keepends=True)
    in_section, last = False, None
    for i, line in enumerate(lines):
        if line.startswith("### Section "):
            in_section = line.startswith(f"### Section {section}:")
        elif in_section and _SUBSECTION_RE.match(line.strip()):
            last = i
    if last is None:
        raise ParityError(
            f"negative control: no numbered subsection in Section {section}"
        )
    lines.insert(last, new_line + "\n\n")
    return "".join(lines)


def _last_label(canonical_md: str, section: str) -> str:
    act, _ = normative_text(
        canonical_md, label="canonical source.md", strip_annotations=False
    )
    return act[section][-1][0]


def negative_controls(
    benchmark_md: str, canonical_md: str, exceptions: list[ParityException]
) -> list[str]:
    """Prove the comparison can fail. Returns a failure per control that stayed green."""
    failures: list[str] = []

    mutated, expected_ref = _first_normative_word(canonical_md)
    found = compare(benchmark_md, mutated, exceptions)
    if not any(f.startswith(expected_ref) for f in found):
        failures.append(
            f"negative control: a changed word in {expected_ref} was not reported"
        )

    label = _last_label(canonical_md, "6")
    duplicated = _insert_after_section_line(
        canonical_md,
        "6",
        f"({label}) An applicant aged 60 or over is exempt in all cases.",
    )
    found = compare(benchmark_md, duplicated, exceptions)
    if not any(
        f.startswith(f"§6({label}): subsection number appears twice") for f in found
    ):
        failures.append(f"negative control: a duplicated §6({label}) was not reported")

    quoted = _insert_after_section_line(
        canonical_md,
        "6",
        "> Note: an applicant with 1000 flight hours is exempt at any age.",
    )
    found = compare(benchmark_md, quoted, exceptions)
    if not any(f.startswith("§6: annotation-style line") for f in found):
        failures.append(
            "negative control: a blockquote in canonical §6 was not reported"
        )

    for exc in exceptions:
        found = compare(
            benchmark_md, canonical_md, [e for e in exceptions if e is not exc]
        )
        if not any(f.startswith(exc.ref) for f in found):
            failures.append(
                f"negative control: removing the {exc.ref} exception did not fail"
            )
    if not exceptions:
        failures.append(
            "negative control: no exceptions to remove (expected at least §5A(3))"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--canonical",
        type=Path,
        default=CANONICAL,
        help="canonical Act (default: %(default)s)",
    )
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=EXCEPTIONS,
        help="reviewed exceptions (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    try:
        lock = load_lock()
        exceptions = load_exceptions(args.exceptions)
        benchmark_md = fetch_benchmark(lock)
        canonical_md = args.canonical.read_text()
        print(
            f"benchmark copy: {lock['repository']}@{lock['commit'][:12]} {lock['path']} ({lock['digest'][:19]}...) verified"
        )
        canonical_digest = (
            "sha256:" + hashlib.sha256(canonical_md.encode("utf-8")).hexdigest()
        )
        print(
            f"canonical Act:  {args.canonical.relative_to(ROOT) if args.canonical.is_relative_to(ROOT) else args.canonical} ({canonical_digest[:19]}...)"
        )
        failures = compare(benchmark_md, canonical_md, exceptions)
        if failures:
            print(
                f"\nFAIL: {len(failures)} normative difference(s) between the canonical Act and the benchmark copy:"
            )
            for failure in failures:
                print(f"  - {failure}")
            print(
                "\nRestore parity, or record a reviewed exception in PARITY_EXCEPTIONS.yaml with a reason."
            )
            return 1
        control_failures = negative_controls(benchmark_md, canonical_md, exceptions)
    except ParityError as exc:
        print(f"FAIL: {exc}")
        return 1

    if control_failures:
        print("\nFAIL: the parity check could not be shown to catch a difference:")
        for failure in control_failures:
            print(f"  - {failure}")
        return 1

    sections = len(
        normative_text(
            canonical_md, label="canonical source.md", strip_annotations=False
        )[0]
    )
    print(
        f"PASS: {sections} normative sections match; {len(exceptions)} reviewed exception(s): "
        + ", ".join(e.ref for e in exceptions)
    )
    print(
        "PASS: negative controls - a changed word, a duplicated subsection, a canonical "
        "blockquote and each removed exception are caught"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
