# Performance: Speed, Cost, and Determinism

> See the [main README](../README.md) for the headline benchmark table.
>
> Measured against `api.aethis.ai` production endpoint.

## Evaluation speed

| | First request | Subsequent (cached) | 1000 evaluations |
|--|--------------|--------------------:|------------------:|
| **Aethis Engine** | 2-30ms | **<1ms** | **<1 second** |
| LLMs | 1-5 seconds | No cache | 25-60 minutes |

The engine compiles rules to constraints on first request, then evaluates
from cache. LLMs re-process the full context on every request.

## Timing breakdown

Typical cached evaluation:
```
Total: 2.4ms
  Compilation: 0.4ms  (cache hit)
  Evaluation:  2.0ms  (constraint solving)
```

Cold start (first request):
```
Total: 25-35ms
  Compilation: 20-30ms  (compile rules)
  Evaluation:  2-5ms    (constraint solving)
```

## Cost at scale

| Evaluations | Aethis Engine | GPT-5.4 | Claude Sonnet | GPT-5.4-mini |
|------------:|--------------:|--------:|--------------:|-------------:|
| 1,000 | $0 | ~$50 | ~$10 | ~$5 |
| 100,000 | $0 | ~$5,000 | ~$1,000 | ~$500 |
| 1,000,000 | $0 | ~$50,000 | ~$10,000 | ~$5,000 |

## Reproduce

```bash
# See timing per test (include_timing is on by default)
uv run run_tests.py construction-all-risks/
```
