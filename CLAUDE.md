# CLAUDE.md

Agent notes for `aethis-examples`. Human-facing docs in [README.md](README.md).

## What this is

The internal source-of-truth repo for the **public** Aethis demo examples. Files here are published to the public GitHub repo `Aethis-ai/aethis-examples` via `scripts/publish.sh` — a clean rsync that drops a single-commit snapshot into the public tree (no history, no internal comments).

Work here freely, but **assume anything you write will be made public**.

## Dev loop

```bash
# Run a specific example's tests against prod
uv run run_tests.py spacecraft-crew-certification/

# Publish a worked example (FSM) end-to-end — regenerates sections, slugs them, composes rulebook
cd uk-free-school-meals
AETHIS_API_KEY=$(pull-internal-key) ANTHROPIC_API_KEY=$(...) bash scripts/publish-to-production.sh

# Push the public snapshot
bash scripts/publish.sh       # reviews diff, then commits + pushes to Aethis-ai/aethis-examples
```

## Layout

- [run_tests.py](run_tests.py) — shared runner for any example (reads `aethis.yaml` + tests)
- [llm_comparison.py](llm_comparison.py) — the benchmark runner (requires OPENAI/ANTHROPIC keys)
- Per-example directories:
  - `spacecraft-crew-certification/` — simple enum + date example
  - `construction-all-risks/` — 5-level exception chain
  - `consumer-credit-prequalification/` — affordability thresholds
  - `uk-free-school-meals/` — multi-section rulebook with `A AND (B OR C)` composition
- `_template/` — scaffold for a new example
- `results/` — benchmark artefacts rendered into the public README
- `scripts/publish.sh` — rsync to public repo
- `scripts/publish-to-production.sh` (per-example, where present) — regenerate + publish to api.aethis.ai

## Gotchas

- **Everything here is reproducibly public.** Per `.claude/rules/public-repos.md`: no trade secrets, no internal identifiers in comments, no DSL syntax in guidance hints. Use public-facing terminology only ("eligibility engine", "rule bundle", "satisfied/not_satisfied/pending").
- **Bundle IDs in examples must be alive in prod.** When an example references a `bundle_id` or slug, it has to currently exist on `api.aethis.ai`. Paul hit this when docs referenced bundles that didn't exist — [mintlify-docs#3](https://github.com/Aethis-ai/docs/issues/3). Verify with `curl api.aethis.ai/api/v1/public/bundles` before shipping.
- **`outcome_logic` is an Expr AST.** The `publish-to-production.sh` script for UK FSM historically shipped `{"expr": "A AND (B OR C)"}`; the server now rejects that (aethis-core dd518b0). Use the structured `op` / `field_ref` / `const` shape as in [uk-free-school-meals/scripts/publish-to-production.sh](uk-free-school-meals/scripts/publish-to-production.sh).
- **`publish-to-production.sh` regenerates sections from scratch.** It deprecates the previous active bundles, calls `aethis generate` per section (burns Anthropic quota), and creates a new rulebook. Not something to run casually — only when you intend to cut a new canonical version.

## See also

- Workspace operational index: [../docs/OPERATIONAL_INDEX.md](../docs/OPERATIONAL_INDEX.md)
- Recipes for agent-consumable versions of these flows: [docs.aethis.ai/recipes](https://docs.aethis.ai/recipes/author-a-rule)
