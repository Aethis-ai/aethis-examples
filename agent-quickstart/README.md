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

> **This script sends no Aethis credential.** Public showcase rulesets evaluate
> anonymously, and the environment handed to the MCP server has `AETHIS_API_KEY`
> stripped out, so a key sitting in your shell cannot silently attribute the run
> to your tenant and quota — if one is set, the script says so and withholds it.
>
> One caveat worth stating plainly: the MCP server can still find a key you
> stored locally with `aethis login` (macOS Keychain, or
> `~/.config/aethis/credentials`). This script cannot reach into that store to
> suppress it. If you have logged in before and want a genuinely anonymous run,
> check with `security find-generic-password -s aethis-cli -a api_key` (macOS)
> or `ls ~/.config/aethis/credentials`.
>
> Authoring your own rulesets is invite-only and is not part of this quickstart.

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
dependency set is declared inline in the script (PEP 723) with direct versions and a compatible Python MCP SDK range —
`langchain==1.3.14`, `langchain-anthropic==1.5.2`, `langchain-mcp-adapters==0.3.0`,
`mcp>=1.24.0,<2` (the Python adapter supports MCP SDK 1.x),
`rfc8785==0.1.4` for public input-identity checks,
and `aethis-mcp@0.17.4` for the MCP server.

Setup is identical on Linux and macOS. If you do not have `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Cost and data flow — read before running

**Cost.** The Aethis side is free: public rulesets evaluate anonymously, with no
key and no billing (the anonymous tier is capped at 500 evaluations per IP per
day). The model side is **billed to your own Anthropic account**. Agent mode is
bounded to three model turns, each capped at 1,024 output tokens, with one retry
per turn (at most six provider requests). Pick a cheaper model with `--model` or
`AETHIS_QUICKSTART_MODEL` if you plan to run it repeatedly. Current model prices:
[platform.claude.com/docs/pricing](https://platform.claude.com/docs/en/pricing).

**Data flow.** Two hops leave your machine:

| Data | Goes to | Notes |
|---|---|---|
| The question text, the tool schemas, and the tool results | Anthropic (`api.anthropic.com`) | Standard model-provider inference. Subject to Anthropic's terms and retention. |
| The field values the agent extracts (here: `space.crew.species`) | Aethis (`api.aethis.ai`) | Anonymous request. The response carries a hash of the inputs, not the inputs. |
| The whole trace — prompts, tool calls, tool results | LangSmith (`api.smith.langchain.com`) | **Only if you have LangChain tracing switched on.** `LANGSMITH_TRACING` or `LANGCHAIN_TRACING_V2` in your shell is a common default for anyone doing LangChain work, and it is easy to forget it applies here too. Unset them for a two-hop run. |

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
| The decision is about the ruleset you asked for | An agent that wanders to another ruleset cannot be reported as proof about this one |
| **Every** criterion the explanation reports carries a publish-validated source reference | Per criterion, not in aggregate: one uncited criterion is one rule whose authority the reader cannot check, and a pending criterion is still a published rule. Each reference needs a title, issuing authority, HTTPS target, sha256 digest, licence, verification time, verbatim quote and deep link (`locator` is optional, and displayed when present) |

Failure is loud and specific — it names each missing field rather than
degrading quietly.

**What the citation check does not do.** It verifies that each reference is
*shaped* like a checkable citation: the digest is a well-formed `sha256:<hex>`,
the target is HTTPS, the quote is non-empty. It does **not** fetch the cited
document and recompute the digest, and it does not re-verify the quote at run
time — the engine does that once, at publish time. So a passing run means "this
decision carries citations with checkable digests", not "the citations have been
re-checked just now".

The parser is deliberately strict about the fence itself: `aethis_decide`
returns exactly one `<api_response>` block, so a payload carrying two is refused
rather than resolved by picking one.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Proven. Every check above passed. |
| `2` | Not proven — a prerequisite is missing, the run timed out, or a check failed. The output names which. |
There is no partial-proof mode. A run succeeds only when it has the real tool
call, terminal decision, immutable identity, replay handles, no blocking field
errors, and every required citation.

## Options

| Flag | Environment variable | Default |
|---|---|---|
| `--tool-only` | — | off |
| `--engine-url` | `AETHIS_API_URL` | `https://api.aethis.ai` |
| `--ruleset` | `AETHIS_QUICKSTART_RULESET` | `aethis/spacecraft-crew-certification` |
| `--model` | `AETHIS_QUICKSTART_MODEL` | `claude-opus-4-8` |
| `--mcp-spec` | `AETHIS_MCP_SPEC` | `aethis-mcp@0.17.4` |
| `--timeout` | `AETHIS_QUICKSTART_TIMEOUT` | `300` (seconds) |

Nothing here ever prompts, and every call is bounded by `--timeout`, so the
script is safe to run from CI or an unattended job.

Pass `--evidence-file evidence.json` to retain a strict, credential-free JSON
artifact after a proven run. It includes the public command parameters, the
verified decision envelope, elapsed time, and either the raw tool-only result or
the agent's actual tool-call and tool-result messages. The file is written only
after every proof check passes; it is never a partial-proof artifact.

## Tests

```bash
uv run agent-quickstart/smoke_test.py
```

Deterministic, offline, and credential-free. The tests build the **real**
LangGraph agent and run it against a scripted model and a stubbed Aethis tool,
then assert on the decision envelope — never on the model's prose. They cover
the passing case, a run where the agent skips the tool, an evaluator that
predates the contract, a verdict beside blocking errors, malformed citations,
a decision about the wrong ruleset, an uncited criterion, ambiguous fenced
output, the process exit codes (0/2/3), the fact that no Aethis credential
reaches the MCP child process (and that withholding one is announced), and both
real tool-output wire shapes.

They are offline in the strong sense: `AETHIS_*`, `ANTHROPIC_*`, `LANGSMITH_*`
and `LANGCHAIN_*` are all scrubbed from the environment at import, so a shell
with tracing switched on cannot turn a test run into a network upload.

[`fixtures/`](fixtures/) holds the recorded inputs and documents where each came
from. The tool-output payloads under [`fixtures/wire/`](fixtures/) were captured
from the aethis-mcp servers themselves — `0.15.1` returns bare JSON, `0.16.0`
wraps the payload in an `<api_response>` fence — so the parser is tested against
what the servers actually emit rather than an approximation. One test recomputes
the recorded citation's digest from the source file in this repo and checks the
quoted text occurs there verbatim, so the fixture cannot drift into fiction.

Lint runs under a pinned, repo-scoped configuration so "clean" is reproducible:

```bash
uvx ruff@0.16.0 check agent-quickstart
```

Both run in CI on every pull request that touches this directory
([`.github/workflows/agent-quickstart.yml`](../.github/workflows/agent-quickstart.yml)),
with no credentials in the environment.

Decimal inputs use the field types from a correlated schema with the same immutable
identity as the decision. A missing or mismatched schema cannot certify decimal
normalisation. Malformed tool requests and inconsistent structured tool results
also fail the proof check.

## Known limitation

If an evaluator does not supply immutable identity and source references, the
strict run exits `2` and names the missing evidence. Point `--engine-url` at an
evaluator that serves the required contract; do not treat incomplete evidence
as a quickstart success.

## See also

- [LangGraph integration recipe](https://docs.aethis.ai/recipes/langgraph-integration) — the long-form version of the pattern this script uses.
- [Decision envelope](https://docs.aethis.ai/concepts/decision-envelope) — every field in the response and how to use it for audit.
- [MCP server](https://github.com/Aethis-ai/aethis-mcp) — the full tool list and stdio configuration.
