# Showcase provenance

A decision this engine produces is only as trustworthy as the reader's ability
to check it. "Trust us, it follows the rules" is exactly the claim a
probabilistic system also makes, and the reason it cannot be relied on. So the
bar here is higher and much more boring: for every showcased ruleset, every
criterion that participates in the decision names the passage it rests on, and
that passage can be fetched, digested and read.

This directory holds the machinery that makes that claim checkable rather than
asserted.

## The claim, stated precisely

A public surface may say a showcased decision is traceable to its source only
when, for that ruleset:

- **every** criterion the ruleset evaluates carries at least one source
  reference - not most of them, and not "the important ones";
- each reference names a title, an issuing authority and a locator, over a
  plain HTTPS target with no credentials and no private destination;
- each reference is bound to a **content digest**, so it cites a version of a
  document rather than an address that may since have changed;
- each reference carries the **verbatim passage** it relies on, and that
  passage actually occurs in the digested bytes;
- the text is reproduced under a licence that permits it.

An opaque citation key, a link that merely resolves, or a summary in place of a
quote all fail. Those are the failure modes that make a citation feel rigorous
without being rigorous.

## Files

| Path | What it is |
|---|---|
| `showcase.yaml` | The launch-showcase registry: which published rulesets the public surface shows, and where each one's citations live. The denominator. |
| `<example>/sources/references.yaml` | Per showcase: the cited documents, the passages, and the criterion-to-citation mapping. |
| `showcase.lock` | Independent record of the claimed showcase slugs, so an entry cannot vanish from the registry unnoticed. Its absence fails the load. |
| `corpus-exemptions.yaml` | Owned, dated exemptions from the corpus sweep. An exemption is not a fix; every entry is reported on each run. |
| `../scripts/restricted-phrases.txt` | The subject-matter boundary, in plaintext. Internal only - `scripts/` is excluded from the public mirror. |
| `fixtures/*.explain.json` | A cached capture of each ruleset's live explanation, for offline runs. Diffed against the engine, never trusted as the denominator. |
| `check_provenance.py` | The gate. Fetches, digests and quote-checks every citation, and reports coverage. |
| `publish_showcase.py` | Verifies an identified candidate and previews targets. Publication refuses until the API can bind the write to that graded candidate. |
| `probe_staging.py` | Asks a deployed engine what it actually serves, and checks it the way a sceptic would. |
| `selftest.py` | Semantics, safety and non-vacuity tests. No network. |
| `evidence/` | The generated coverage artefact. |

## Two coverage numbers, and why both exist

`check_provenance.py` reports each showcase twice, because "we wrote the
citations down" and "a visitor receives them" are different achievements:

- **manifest coverage** - criteria bound to a *verified* citation: fetched,
  digested, quote-checked. This repository controls it, and it must be 100%.
  An `--offline` run does none of that, so it reports no verified count at all
  rather than borrowing the count of criteria that merely declare one.
- **served coverage** - criteria whose complete resolved references match the
  independently verified manifest targets on both live `/explain` and `/decide`
  paths, including metadata, normalized quote and source digest. Both paths must
  return HTTP 200 in their own explanation envelopes and serve identical
  references. Required replay and criterion fields must satisfy the consumed
  leaf DTO and layered-builder contract; the empty request input hash must
  match, and blocking errors forbid a terminal verdict. A response with
  missing or mismatched references fails
  the gate. Without a live read, or in an offline run, coverage is unknown and
  the showcase cannot authorise a claim. Legacy v1 references may omit the
  additive snapshot marker; when present it must equal the source digest.
  Schema-v1 references are URL references: artefact target markers or nonempty
  artefact IDs are invalid. A failed HTTP observation supplies unknown coverage,
  even when its error body contains otherwise valid reference data.
  Safe final redirect URLs and their deep links must match the verified target;
  a changed final target fails closed even if its bytes remain identical.

A showcase becomes eligible for the public claim only when both are 100% and
the denominator came from a live engine and both observed paths passed without
failures. The checker, artifact verifier and probe share this observed verifier.
A single-path helper reports its own count as `served_path_eligible` and never
authorizes `claim_eligible`. A null, unavailable or malformed decision
explanation withholds the combined count even if `/explain` is intact. Malformed
criterion and reference objects produce diagnostics rather than a traceback.
Unknown offline evidence is withheld; missing or mismatched live references
are hard failures, even when a registry note documents a pending publication.

## The denominator cannot be shrunk

The list of criteria that must be cited comes from a **live** `GET /explain`,
not from anything committed here. `/explain` is anonymous, so there is no
reason to trust a file for this - and a denominator stored in an editable file
is a convention, not a guarantee. Leaving a criterion out of `references.yaml`
does not remove it from the total; it produces an `uncited_criterion` failure.
The committed fixture is a cache for `--offline` runs, and the gate diffs it
against the live response and reports `fixture_drift` on any disagreement.

This matters because the easiest way to reach a 100% traceability figure is to
quietly decide some criteria do not need a source. An earlier version of this
gate read the denominator from the fixture; deleting one criterion from that
file took the suite to a green 9/9 for a ruleset the engine evaluates ten
criteria for. Every guarantee on this page is now asserted by breaking it in
`selftest.py`, because that one was documented before it was true.

## Before a republish can move served coverage off zero

Supplying `source_targets` at publish time is not enough, and this is the part
that is easy to get wrong. The engine resolves targets **keyed by the citation
keys the ruleset's own criteria declare**; a ruleset that declares none
short-circuits to an empty result, and the publish succeeds having resolved
nothing. A target preview does not establish that the engine served those references.

So the sequence is: author the citation keys into each ruleset's criteria
first - `concessionary-travel-pass` is the working example, with
`source_refs=["source.md#source/Section 3: Residency requirement"]` on the
criterion - then prepare targets from the manifest. `publish_showcase.py`
checks an identified candidate and previews its targets. It refuses `--apply`
and direct publication before any write because the existing API chooses the
project latest ruleset independently of that candidate, with no atomic identity
binding. Reading latest before a write does not prevent a concurrent change.
Publication therefore requires a separately reviewed owning workflow; a preview
is never proof that a candidate was published or that its citations were served.

## Running it

```bash
uv run provenance/selftest.py                   # semantics + non-vacuity, offline
uv run provenance/check_provenance.py           # the gate: fetch, digest, quote-check
uv run provenance/check_provenance.py --offline # structure only
uv run provenance/probe_staging.py --self-test  # prove the live probe catches what it claims
uv run provenance/probe_staging.py              # ask a deployed engine what it serves
```

## The evidence artefact is bound to the run that made it

`evidence/coverage.json` carries a `binding`: the commit, and a digest of every
fixture and citation manifest it was computed from. `--verify-artefact`
recomputes that and refuses an artefact whose inputs have moved, whose mode is
not `verified`, or that claims eligibility on a non-live denominator. CI also
regenerates it and diffs, so hand-editing has to survive both.

This exists because it did not: a reviewer hand-set `claim_eligible: true` on
all four showcases and it passed the whole suite. The numbers were correct and
nothing was checking they were the numbers a run produced.

## Three things the gate cannot be talked out of

- **A criterion the engine evaluates must be cited.** Omission is a failure,
  not a smaller total.
- **A self-cited document must match the bytes being cited.** Three showcases
  cite documents this repository publishes; each declares a `local_path`, and
  the gate compares the local file to the pinned digest. Editing the local copy
  without republishing goes red.
- **A showcase cannot leave the registry quietly.** `showcase.lock` records the
  claimed slugs; dropping one from `showcase.yaml` fails until the lock is
  updated in the same change. Deleting the lock does not disable the check -
  its absence is itself a failure.
- **The whole corpus is swept, not just the quoted passages.** A restricted
  phrase anywhere in a cited document fails the gate; a known one that someone
  else must fix needs an owned entry in `corpus-exemptions.yaml`.

## Fixtures belong to the environment you are probing

`fixtures/*.explain.json` is a capture of a published ruleset, and different
environments publish different versions. Capturing from one engine and probing
another produces `criterion_absent` failures that are real drift reports about
the wrong pair of things. Refresh the fixtures from the engine you are about to
probe:

```bash
uv run provenance/check_provenance.py --refresh-fixtures --base-url "$AETHIS_BASE_URL"
uv run provenance/probe_staging.py     --base-url "$AETHIS_BASE_URL"
```

The committed fixtures track the canonical published rulesets on
`api.aethis.ai`, because that is what the public surface shows.

## Adding or changing a citation

1. Read the passage in the source document. Copy it exactly - do not
   summarise, and do not tidy the wording.
2. Add it under `references:` in the showcase's `references.yaml`, and map the
   criteria that rest on it under `criteria:`.
3. Re-pin the digests: `uv run provenance/check_provenance.py --refresh-digests`.
   Pin only after you have read the passage; the digest records that you did.
4. Run the gate. A `quote_not_found` means the quote has drifted from the text,
   which is a real finding, not an obstacle to route around.

If a cited document is republished, the gate goes red with `digest_mismatch`.
The fix is to read the new text and confirm the rule still says what the
citation claims - then re-pin. Re-pinning without re-reading defeats the entire
mechanism.

The probe reads each endpoint's own explanation shape and rejects an ambiguous flat duplicate on `/decide`. Each path reports its own verified count. The combined count is withheld on any failure; an intact `/explain` cannot mask a broken evaluated explanation. Live claim reads require HTTP 200; partial or other successful-status bodies are not complete observations.

Both owning self-test entry points deny HTTP, DNS and socket connections for the
whole suite. The artifact-verification control injects both endpoint responses
and local source fetches; an attempted network call fails even if code catches
the access error. The earlier 89-case result predates this enforced boundary
and must not be described as verified offline. Historical coverage artifacts
and source-drift failures remain unchanged by this consumer repair.

The observed pair also retains its requested selector, resolved ruleset IDs,
aliases, published versions, content digests and decision. An alias must resolve
to a distinct immutable ID; an exact-ID selector must match that ID. Both routes
must resolve the same cut, and the decision must be `eligible`, `not_eligible` or
`undetermined`. These observations are substantive artifact fields, so a fresh
identity change cannot reproduce an earlier artifact merely by keeping its
references unchanged.

Real source transport/read errors become `fetch_failure` or `fetch_timeout`
diagnostics and withhold the claim. Each cited URL is attempted once per paired
verification, including failed reads. Artifact verification rejects fresh HOLDs;
publisher preview raises `PublishRefused`. Programming errors remain visible.

The verifier retains both complete route observations. Artifact comparison
excludes only expected per-invocation decision ID/time/timing variation after
validating both stored and fresh contracts; deletion or malformed required
fields still fails. Top-level `undetermined` with layered `pending` is a valid
builder shape, and blocking errors can override a nested terminal result to
`undetermined`.

Fetched source bodies must match their declared Content-Length, including an
actual bounded HTTP reader that silently returns a short body. Legal HTTP
space/tab around Content-Length and leading zeros are accepted; only ASCII
decimal lengths reach bounded conversion. Oversized or malformed lengths fail
closed. Untrusted object-envelope JSON decoding normalizes integer-limit and
nesting failures at the decoder boundary; reader/transport programming errors
remain visible. Quote prefix
and suffix selectors must occur around the same normalized exact quote; merely
constructing the corresponding fragment is insufficient. Existing captures
may therefore remain HOLD under the strengthened definition. No capture,
source bytes or pins are changed automatically. Expected endpoint I/O/parse
failures are reported; programming errors remain visible. Remote preview
requires HTTP200 and a complete identified explanation contract.

The same bounded HTTP reader now protects source reads, both API JSON routes,
HTTP error JSON and remote candidate preview: one read capped at 10 MiB plus
one sentinel byte, independently normalized declared length, and rejection
of short bodies or unread declared bytes. A complete zero-padded declaration
remains valid even when the standard HTTP reader discards its parsed length.
All decoded envelopes and injected route observations are traversed iteratively
before retention, recursive copying or comparison: maximum depth 64 and
100,000 value nodes, including unused extras. Exceeding these bounds withholds
the claim and produces a bounded artifact refusal. These are consumer safety
bounds, not a new producer identity contract.
