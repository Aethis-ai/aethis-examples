# aethis-examples

LLMs are unreliable for rule evaluation. They hallucinate exceptions, miss nested conditions, and give different answers on retry. These examples show where LLM-based decision workflows fail — and how deterministic rule bundles fix it.

Each example includes source legislation, golden test cases, and a one-command test runner that calls the live API. No API key needed.

## The problem

We tested frontier LLMs on 11 insurance coverage scenarios involving a five-level exception chain:

| | Accuracy | Speed | Deterministic | Explainable | Regulated use |
|--|----------|-------|:---:|:---:|:---:|
| **Aethis Engine** | **100%** | **<5ms** | ✅ | ✅ | ✅ |
| GPT-5.4 | 100% | 2-5s | ❌ | ❌ | ❌ |
| Claude Opus 4.6 | 100% | 2-5s | ❌ | ❌ | ❌ |
| Claude Sonnet 4.6 | 91% | 1-3s | ❌ | ❌ | ❌ |
| GPT-5.4-mini | 82% | 1-2s | ❌ | ❌ | ❌ |
| GPT-5.3 (ChatGPT) | 27% | 2-5s | ❌ | ❌ | ❌ |

Flagship LLMs match the engine on accuracy — but accuracy is table stakes. In regulated workflows, decisions must be deterministic, explainable, and non-stochastic. The model most people use daily (GPT-5.3) gets 73% wrong.

[Per-test breakdown →](results/llm-vs-engine.md) | [Speed and cost →](results/performance.md)

```bash
# Reproduce it yourself (requires OPENAI_API_KEY + ANTHROPIC_API_KEY)
uv run llm_comparison.py construction-all-risks/ --models gpt-5.4 claude-sonnet-4-6 gpt-5.4-mini
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
