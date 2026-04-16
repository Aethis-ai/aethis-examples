# LLM vs Deterministic Engine: Per-Test Breakdown

> See the [main README](../README.md) for the headline benchmark table.
>
> Last verified: 2026-04-06 | Full source text, no truncation, no pattern hints

## Test suite: Construction All Risks — 5-level exception chain

11 scenarios testing a synthetic insurance endorsement with nested exceptions,
cross-references, and conditional overrides. No pattern hints in the source
legislation — LLMs must reason from the raw policy wording.

| # | Test | Expected | GPT-5.4 | Opus | Sonnet | Mini | Engine |
|---|------|----------|---------|------|--------|------|--------|
| 1 | Rectification — absolute exclusion | not_eligible | Pass | Pass | Pass | Pass | Pass |
| 2 | Consequential damage — carve-back | eligible | Pass | Pass | Pass | Pass | Pass |
| 3 | Access damage, standard project | not_eligible | Pass | Pass | Pass | Pass | Pass |
| 4 | Access damage, enhanced (£150M) | eligible | Pass | Pass | Pass | Pass | Pass |
| 5 | Design defect, enhanced | not_eligible | Pass | Pass | **Fail** | **Fail** | Pass |
| 6 | Design defect, pioneer (£600M) | eligible | Pass | Pass | Pass | Pass | Pass |
| 7 | Plant equipment — excluded | not_eligible | Pass | Pass | Pass | Pass | Pass |
| 8 | Late notification | not_eligible | Pass | Pass | Pass | Pass | Pass |
| 9 | Pioneer + known defect — blocked | not_eligible | Pass | Pass | Pass | Pass | Pass |
| 10 | Pioneer + known + engineer — unblocked | eligible | Pass | Pass | Pass | **Fail** | Pass |
| 11 | Pioneer + defect not known | eligible | Pass | Pass | Pass | Pass | Pass |

**Sonnet fails** on test #5: says "eligible" for a design defect on an enhanced
project — misses the design exclusion (level 2 of the exception chain).

**Mini fails** on tests #5 and #10: misses both the design exclusion AND the
engineer assessment override (levels 2 and 5).

## Reproduce

```bash
# Run all tests (no API key needed)
uv run run_tests.py construction-all-risks/

# Compare against LLMs (requires OPENAI_API_KEY + ANTHROPIC_API_KEY)
uv run llm_comparison.py construction-all-risks/ --models gpt-5.4 claude-sonnet-4-6 gpt-5.4-mini
```
