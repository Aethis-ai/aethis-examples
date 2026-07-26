# Agent quickstart

A LangGraph agent that uses an Aethis decision — and proves it did.

Clone the repo, set one key, run one command:

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # your own model-provider key
uv run agent-quickstart/quickstart.py
```

The agent reads a plain-English question, calls the Aethis eligibility engine as
an MCP tool, and prints the outcome **next to the evidence**: the pinned ruleset
identity, the replay handles, and the verbatim passages the rules cite.

> **No Aethis credential is required.** Public showcase rulesets evaluate
> anonymously. Authoring your own rulesets is invite-only and is not part of
> this quickstart.

## Try it first without spending anything

```bash
uv run agent-quickstart/quickstart.py --tool-only
```

`--tool-only` skips the model provider entirely: it calls the Aethis tool
directly over MCP and runs the same proof checks. No provider key, no tokens, no
cost. Use it to confirm Node and network access work before the full run.

## What you need

| Prerequisite | Why | Check |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Runs the script and resolves its pinned dependencies | `uv --version` |
| Node.js 18 or newer | `npx` fetches the Aethis MCP server | `npx --version` |
| Python 3.11 or newer | Declared in the script header; `uv` will fetch one if needed | `uv python list` |
| `ANTHROPIC_API_KEY` | **Agent mode only.** Your own key, billed to your own account | `echo ${ANTHROPIC_API_KEY:+set}` |
| Outbound HTTPS | `api.aethis.ai` (the evaluator) and `registry.npmjs.org` (the MCP server) | — |

Nothing is installed globally and nothing is written outside `uv`'s cache: the
dependency set is declared inline in the script (PEP 723) and pinned exactly —
`langchain==1.3.14`, `langchain-anthropic==1.5.2`, `langchain-mcp-adapters==0.3.0`,
and `aethis-mcp@0.15.1` for the MCP server.

Setup is identical on Linux and macOS. If you do not have `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Cost and data flow — read before running

**Cost.** The Aethis side is free: public rulesets evaluate anonymously, with no
key and no billing (the anonymous tier is capped at 500 evaluations per IP per
day). The model side is **billed to your own Anthropic account**. One run of the
default model is a few thousand tokens — cents, not dollars — but it is your
spend, and a loop over this script is your spend too. Pick a cheaper model with
`--model` or `AETHIS_QUICKSTART_MODEL` if you plan to run it repeatedly. Current
model prices: [platform.claude.com/docs/pricing](https://platform.claude.com/docs/en/pricing).

**Data flow.** Two hops leave your machine:

| Data | Goes to | Notes |
|---|---|---|
| The question text, the tool schemas, and the tool results | Anthropic (`api.anthropic.com`) | Standard model-provider inference. Subject to Anthropic's terms and retention. |
| The field values the agent extracts (here: `space.crew.species`) | Aethis (`api.aethis.ai`) | Anonymous request. The response carries a hash of the inputs, not the inputs. |

**Everything in this example is synthetic.** The applicant is fictional, the
statute is a fictional one written for these examples, and no personal data of
any kind is involved. Do not put real personal data through a public quickstart
— run against your own deployment, with your own key, for that.

## What "with proof" means

The agent's answer is prose. Prose is not evidence: a model that never called
the tool can still write a fluent, confident, wrong verdict. So the quickstart
ignores what the agent *said* and inspects the structured decision envelope the
agent actually *received*, then refuses to report success unless all of this
holds:

| Check | Why it matters |
|---|---|
| The Aethis tool was really called | Otherwise the answer is the model's opinion |
| `decision` is `eligible`, `not_eligible` or `undetermined` | The only outcomes the engine defines |
| `ruleset_id` + a resolved `ruleset_version` + `content_digest` | Pins the exact rule artefact. `unknown` is rejected |
| `decision_id` + `inputs_hash` | Addresses and replays the decision without echoing the inputs |
| `engine_version` | The build that produced it |
| No verdict beside blocking `field_errors` | A verdict must never be computed from rejected input |
| Every criterion carries publish-validated source references | Title, issuing authority, HTTPS target, locator, digest, licence, verification time, verbatim quote, deep link |

Failure is loud and specific — it names each missing field rather than
degrading quietly.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Proven. Every check above passed. |
| `2` | Not proven — a prerequisite is missing, the run timed out, or a check failed. The output names which. |
| `3` | Partial proof (`--allow-partial-proof` only). Never treat as success. |

`--allow-partial-proof` waives the immutable-identity and source-reference half
of the contract, for pointing the quickstart at an evaluator that predates it.
The core invariants still hold: the tool call must have happened, the outcome
must be valid, the replay handles must be present, and a verdict still may not
sit beside blocking errors. It exits `3` and prints exactly what was waived, so
no gate can mistake it for a pass.

## Options

| Flag | Environment variable | Default |
|---|---|---|
| `--tool-only` | — | off |
| `--engine-url` | `AETHIS_API_URL` | `https://api.aethis.ai` |
| `--ruleset` | `AETHIS_QUICKSTART_RULESET` | `aethis/spacecraft-crew-certification` |
| `--model` | `AETHIS_QUICKSTART_MODEL` | `claude-opus-4-8` |
| `--mcp-spec` | `AETHIS_MCP_SPEC` | `aethis-mcp@0.15.1` |
| `--timeout` | `AETHIS_QUICKSTART_TIMEOUT` | `300` (seconds) |
| `--allow-partial-proof` | — | off |

Nothing here ever prompts, and every call is bounded by `--timeout`, so the
script is safe to run from CI or an unattended job.

## Tests

```bash
uv run agent-quickstart/smoke_test.py
```

Deterministic, offline, and credential-free. The tests build the **real**
LangGraph agent and run it against a scripted model and a stubbed Aethis tool,
then assert on the decision envelope — never on the model's prose. They cover
the passing case, a run where the agent skips the tool, an evaluator that
predates the contract, a verdict beside blocking errors, malformed citations,
and both tool-output wire shapes. `agent-quickstart/fixtures/` holds the
recorded envelopes, each annotated with where it came from; one test recomputes
the recorded citation's digest from the source file in this repo and checks the
quoted text occurs there verbatim, so the fixture cannot drift into fiction.

A recorded run of both modes: [`TRANSCRIPT.md`](TRANSCRIPT.md).

## Known limitation

The evaluator currently deployed at `api.aethis.ai` predates the
immutable-identity and source-reference contract, so a strict run against it
exits `2` and reports the three fields it cannot supply. That is the check
working, not a bug in the quickstart. Until the release candidate is live, use
`--tool-only --allow-partial-proof` to see the full path end to end, or point
`--engine-url` at an evaluator that serves the current contract.

## See also

- [LangGraph integration recipe](https://docs.aethis.ai/recipes/langgraph-integration) — the long-form version of the pattern this script uses.
- [Decision envelope](https://docs.aethis.ai/concepts/decision-envelope) — every field in the response and how to use it for audit.
- [MCP server](https://github.com/Aethis-ai/aethis-mcp) — the full tool list and stdio configuration.
