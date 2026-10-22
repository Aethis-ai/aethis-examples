# Fixtures

Recorded inputs for the quickstart's smoke tests. Every file says where it came
from, because a fixture nobody can trace is indistinguishable from a guess.

## Decision envelopes (`*.decide.json`)

Each carries a `_fixture` key describing its provenance.

| File | What it is |
|---|---|
| `release-contract.decide.json` | A live `/decide` response, hand-completed to the release contract: resolved version, content digest, and a publish-validated citation on **every one of the ten criteria** the explanation reports — the contract is per criterion, not aggregate. Every citation is checkable: each `content_digest` is the sha256 of `../../spacecraft-crew-certification/sources/source.md` and each quote occurs there verbatim, at the section its `locator` names. `test_fixture_citations_are_self_consistent` recomputes both for all ten, so this file cannot drift into fiction. |
| `legacy-engine.decide.json` | Recorded verbatim from `api.aethis.ai` (engine `aethis-core@0.46.3`), which predates the contract. The tests assert it is **rejected** in strict mode. |
| `blocking-errors.decide.json` | Hand-built impossible envelope: a positive verdict beside blocking `field_errors`. The engine contract forbids it; the tests assert it is rejected. |

## Tool-output wire payloads (`wire/*.wire.txt`)

Captured from the aethis-mcp servers themselves — not hand-written — because the
two releases fence tool output differently and a hand-written approximation
would have hidden that. (An earlier draft of these tests did exactly that, and
the parser silently failed on the real 0.16.0 shape.)

| File | Captured from | Shape |
|---|---|---|
| `decide-aethis-mcp-0.15.1.wire.txt` | `npx aethis-mcp@0.15.1` → `aethis_decide` against `api.aethis.ai` | bare pretty-printed JSON |
| `decide-aethis-mcp-0.16.0.wire.txt` | the same call against a local build of aethis-mcp 0.16.0 | preface + `<api_response label="json">` fence |
| `release-contract-aethis-mcp-0.16.0.wire.txt` | `release-contract.decide.json` — with the `_fixture` provenance key removed, since no real server would emit one — passed through aethis-mcp 0.16.0's own exported `fenceData()` | preface + `<api_response label="json">` fence |

`test_recorded_wire_payloads_parse` asserts each shape is what it claims to be
and that the parser recovers the same envelope from both.
