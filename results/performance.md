# Performance: Speed, Cost, and Determinism

> See the [main README](../README.md) for the headline benchmark table.
>
> Measured against `api.aethis.ai` production endpoint.

## Evaluation speed

| | Cold request | Warm request | 1000 warm evaluations |
|--|--------------|-------------:|----------------------:|
| **Aethis Engine** | Hundreds of ms to ~1s when a ruleset compiles cold | **2-10ms typical** | **Seconds, not minutes** |
| LLMs | 1-5 seconds | No deterministic cache | 25-60 minutes |

Figures are client-observed HTTPS round-trips against the production
endpoint, so they include network and API-layer overhead. The engine's
in-process decision evaluation is <1ms median — the canonical latency
figure cited in the benchmark paper.

The engine compiles rules to constraints on first request, then evaluates
from cache. LLMs re-process the full context on every request.

## Timing breakdown

Typical warm evaluation (client-observed):
```
Total: 2-10ms round-trip
  In-process evaluation: <1ms median
  Network + API layer:   remainder
```

Cold request after cache eviction or first compile:
```
Total: hundreds of ms to ~1s for larger examples
  Compilation: dominates the request
  Evaluation:  usually single-digit ms
```

## Cost at scale

| Evaluations | Aethis Engine | GPT-5.4 | Claude Sonnet 4.6 | GPT-5-mini |
|------------:|--------------:|--------:|------------------:|-----------:|
| 1,000 | $0 | ~$50 | ~$10 | ~$5 |
| 100,000 | $0 | ~$5,000 | ~$1,000 | ~$500 |
| 1,000,000 | $0 | ~$50,000 | ~$10,000 | ~$5,000 |

## Reproduce

```bash
# See timing per test (include_timing is on by default)
uv run run_tests.py construction-all-risks/
```
