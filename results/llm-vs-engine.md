# LLM vs Deterministic Engine: Per-Test Breakdown

> See the [main README](../README.md) for the headline benchmark table.
>
> Numbers below are from [Simpson, Kozak, Doake 2026](https://github.com/Aethis-ai/confidently-wrong-benchmark/blob/main/paper/Simpson_Exception_Chain_Collapse_2026.md) (v3.11), Table 8b.
>
> **External validation (paper §6.10):** the same paper reports the engine significantly more accurate than three frontier LLMs across 9 LegalBench tasks (949 held-out cases) by combined paired-binomial McNemar's: *p* < 0.001 vs Sonnet 4.6, *p* = 0.003 vs Opus 4.7, *p* < 0.001 vs GPT-5.4. See [`legalbench/`](https://github.com/Aethis-ai/confidently-wrong-benchmark/tree/main/legalbench) for the full harness.

## Test suite: Construction All Risks — 5-level exception chain

11 scenarios testing a synthetic insurance endorsement with nested exceptions,
cross-references, and conditional overrides. No pattern hints in the source
legislation — LLMs must reason from the raw policy wording.

| Model | Accuracy (N=11) | Wilson 95% CI | Notes |
|--|:--:|:--:|--|
| **Aethis Engine** | **11/11 (100%)** | [74.1%, 100%] | deterministic by construction |
| GPT-5.4 (default reasoning) | 10/11 (90.9%) | [62.3%, 98.4%] | original v3.6/v3.7 figure; the £500M-boundary failure no longer reproduces in the April 2026 replication |
| GPT-5.4 (`reasoning_effort=low`, v3.8 replication) | 11/11 (100%) | [74.1%, 100%] | an earlier 7/11 claim was withdrawn in the paper's v3.8 revision (instrumented replication) |
| GPT-5.3 | 7/11 (63.6%) | [35.4%, 84.8%] | production-tier baseline |
| GPT-4.1-mini | 5/11 (45.5%) | [21.3%, 72.0%] | fails across enhanced cover chain |

**Caveats from the paper:**

- CI widths are ~50pp at N=11; the GPT-5.4-default and GPT-5.3 intervals overlap substantially.
- The 11-scenario sub-study is **underpowered** to detect a 64%-vs-91% effect (power 35.6% at α=0.05; required N≥35 per arm).
- The intra-model reasoning-compute-dependence hypothesis was **withdrawn in v3.8** (no committed script reproduced the original 7/11; instrumented replication returned 11/11). Section 6.9 pre-registers an N=66 replication, not yet run as of v3.11 (July 2026).
- v3.5 of the paper reported GPT-5.3 at 27% (3/11); that figure was a harness-configuration bug (token budget too small for reasoning models). The corrected value is 63.6%.

## Failure pattern

In the March 2026 snapshot, GPT-5.4 failed the pioneer override boundary: `access_500m_design` was
incorrectly rejected (the override applies at >= £500M), while the identical
scenario at £800M was correctly accepted. That specific cell no longer reproduces in the April 2026
replication — itself evidence of the paper's shifting-ground finding (§6.5 Finding 6). The Aethis Engine evaluates
`500 >= 500 = True` with no ambiguity, in either month.

GPT-4.1-mini fails systematically across the enhanced cover chain, treating the
access damage exclusion as absolute and failing to apply the carve-back.

## Reproduce

```bash
# Run all tests (no API key needed)
uv run run_tests.py construction-all-risks/

# Compare against LLMs (requires OPENAI_API_KEY + ANTHROPIC_API_KEY)
uv run llm_comparison.py construction-all-risks/ --models gpt-5.4 claude-sonnet-4-6 gpt-5-mini
```
