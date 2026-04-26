# aethis-examples

LLMs are unreliable for rule evaluation. They hallucinate exceptions, miss nested conditions, and give different answers on retry. These examples show where LLM-based decision workflows fail — and how deterministic rule bundles fix it.

Each example includes source legislation, golden test cases, and a one-command test runner that calls the live API. No API key needed.

**Documentation:** [docs.aethis.ai](https://docs.aethis.ai) · [OpenAPI spec](https://docs.aethis.ai/api-reference/openapi.json) · agents via MCP: `claude mcp add aethis -- npx -y aethis-mcp`

## The problem

Numbers below from the paper ([Simpson, Kozak, Doake, v3.8, 2026](https://github.com/Aethis-ai/confidently-wrong-benchmark/blob/main/paper/Simpson_Exception_Chain_Collapse_2026.md)).

**v3.8 adversarial construction-CAR extension (paper §6.4.1):** 20 newly-authored adversarial scenarios stratified across 5 complexity dimensions. Engine 20/20 (100%) by construction; current frontier models still fail:

| Model | Accuracy (20 scenarios) | Notes |
|--|:--:|--|
| **Aethis Engine** | **20/20 (100%)** | deterministic by construction |
| GPT-5.4 (`reasoning_effort=low`) | 20/20 (100%) | 16–126 reasoning tokens per scenario |
| Claude Sonnet 4.6 | 19/20 (95%) | fails E4 (DE3/LEG3 carveback gap) |
| GPT-5.4 (default) | 19/20 (95%) | **0 reasoning tokens on every scenario** — short-circuits on E4 |
| **Claude Opus 4.7** (current Anthropic strongest) | **18/20 (90%)** | fails E4 + B3 (£499 M boundary) |

Three of four frontier configurations fail the same scenario across both Anthropic and OpenAI families. Reproducible from `confidently-wrong-benchmark/legalbench/tools/replication_run.py` against `dataset/construction-all-risks/scenarios_v3_8_adversarial.yaml`.

**External validation on LegalBench (v3.8, §6.10).** On 9 LegalBench tasks (949 held-out cases, peer-reviewed external benchmark) the engine is significantly more accurate than each of three frontier LLMs by combined paired-binomial McNemar's: *p* < 0.001 vs Sonnet 4.6, *p* = 0.003 vs Opus 4.7, *p* < 0.001 vs GPT-5.4. See [`confidently-wrong-benchmark/legalbench/`](https://github.com/Aethis-ai/confidently-wrong-benchmark/tree/main/legalbench) for the full harness.

**The shifting-ground problem (paper §6.5 Finding 6).** Several v3.7 paper cells closed silently between March and April 2026 under the same model alias — GPT-5.4 on construction-CAR moved from 96.6% to 100%; Opus 4.6 on spacecraft from 89.7% to 98.5%. Frontier-LLM accuracy is a moving target. The Aethis Engine is invariant by construction.

[Per-test breakdown →](results/llm-vs-engine.md) | [Speed and cost →](results/performance.md) | [Full benchmark paper →](https://github.com/Aethis-ai/confidently-wrong-benchmark)

```bash
# Reproduce it yourself (requires OPENAI_API_KEY + ANTHROPIC_API_KEY)
uv run llm_comparison.py construction-all-risks/ --models gpt-5.4 claude-sonnet-4-6 gpt-5-mini
```

## Who this is for

- **Agent builders** who need reliable decisions inside tool-calling workflows
- **LangChain / LangGraph users** replacing brittle prompt chains with provable logic
- **Policy and compliance engineers** who need auditable, explainable decisions
- **Anyone building regulated workflows** where "95% accurate" isn't good enough

## Examples

| Example | Domain | Patterns | Tests |
|---------|--------|----------|-------|
| [Spacecraft Crew Certification](spacecraft-crew-certification/) | Space regulation | Disqualification, AND/OR, exceptions, conditional, enum | 5 |
| [Construction All Risks](construction-all-risks/) | Insurance | Five-level exception chain, IMPLIES, override, early termination | 11 |
| [Consumer Credit Pre-Qualification](consumer-credit-prequalification/) | Lending | Income thresholds, DTI ratios, credit bands, customer exceptions | 8 |

## Run tests

```bash
uv run run_tests.py construction-all-risks/
```

No API key needed. Each test shows the decision, per-group evaluation status, provenance (which source passages informed each rule), and timing:

```
  PASS   Rectification claim — absolute exclusion (Clause 6)
         not_eligible (11/11 fields provided)
         policy_period: passed  insuring_clause: passed  not_rectification: failed
         Timing: 2.4ms (compile 0.4ms, eval 2.0ms)

  PASS   Design defect on enhanced project — not reinstated (Clause 9(2))
         not_eligible (11/11 fields provided)
         enhanced_cover: failed
         Timing: 1.9ms
```

## Inspect decision routes

See how the engine picks the optimal question order and short-circuits as soon as a decision is reached:

```bash
uv run show_routes.py construction-all-risks/
```

```
  Plant equipment — excluded category (Clause 5)
    1. origin = materials      (8 remaining)
    2. value_millions_gbp = 50 (8 remaining)
    3. category = plant_equipment  -> not eligible
       Failed: insured_category
    Decision in 3 steps (of 11 fields)

  Design defect on enhanced project — not reinstated (Clause 9(2))
    1. origin = design             (8 remaining)
    2. value_millions_gbp = 150    -> not eligible
       Failed: enhanced_cover
    Decision in 2 steps (of 11 fields)
```

Different answers lead to different paths. The engine asks only the questions that matter.

## Interactive walk-through

Answer questions one at a time. The engine picks the next most informative question:

```bash
uv run walk_through.py construction-all-risks/
```

## How to use

### With AI agents (MCP)

```bash
claude mcp add aethis -- npx -y aethis-mcp

# Then ask your agent:
# "Is a Vogon eligible for crew certification?"
```

No API key needed for public demo bundles. See [aethis-mcp](https://github.com/Aethis-ai/aethis-mcp).

### With the CLI

```bash
pip install aethis-cli
cd spacecraft-crew-certification
aethis generate --poll
aethis test
aethis publish
```

### As a REST API

```bash
curl -X POST https://api.aethis.ai/api/v1/public/decide \
  -H "Content-Type: application/json" \
  -d '{"bundle_id": "<bundle-id>", "field_values": {"space.crew.species": "Vogon"}}'
```

## Contributing an example

Copy the `_template/` directory:

```bash
cp -r _template/ my-example/
```

Each example follows this structure:

```
my-example/
├── aethis.yaml              # Project config (project name, API key env var)
├── README.md                # What it covers, patterns exercised
├── sources/
│   └── source.md            # The legislation, policy, or specification text
├── guidance/
│   └── hints.yaml           # Domain knowledge hints for the rule generator
└── tests/
    └── scenarios.yaml       # Test cases: inputs + expected outcomes
```

## Related

- [aethis-mcp](https://github.com/Aethis-ai/aethis-mcp) — MCP server for AI agents (npm)
- [aethis-cli](https://github.com/Aethis-ai/aethis-cli) — Python CLI for rule authoring (pip)
- [aethis.ai](https://aethis.ai) — Sign up and get your API key

## License

MIT
