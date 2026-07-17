# Concessionary Travel Pass Act 2051

A synthetic statute modelled on UK primary legislation (cf. the Transport
Act 2000, Part II — Travel Concessions), designed to exercise two
aethis-core authoring-surface features together: the **`years_between`
completed-whole-years date operator**, and the **`GET /graph` ruleset-map
endpoint**.

**Docs:** [Ruleset & rulebook graphs](https://docs.aethis.ai/reference/graph) ·
[docs.aethis.ai](https://docs.aethis.ai)

## What this example covers

| Pattern | Section | Description |
|---------|---------|--------------|
| Disqualifying criterion | S.3 | Not ordinarily UK-resident → immediate rejection, no further checks |
| Completed-years date arithmetic | S.4 | Age route: `years_between(date_of_birth, application_date) >= 66` |
| Alternative route (OR) | S.5 | Disability route qualifies regardless of age |
| Two-group composition | S.6 | `residency_check AND (age_route OR disability_route)` |

### Why `years_between`, not `days_between(...) / 365`

"Reckon age as of a date" sounds like arithmetic (`(application_date -
date_of_birth) / 365`), but that's wrong at leap-year boundaries — a
day-count divided by 365 drifts by roughly a day every four years, and the
DSL is integer-only so a naive division silently truncates besides.
`years_between(start, end)` is a dedicated engine operator that answers the
actual legal question — "has the Nth birthday been reached on or before
`end`?" — exactly, including where the date of birth itself is 29 February
(see the leap-day test cases below). It's authored the same way any other
DSL expression is: from natural-language source text (`sources/source.md`
§2, §4) via the standard generation pipeline — nothing about this example
required hand-writing the operator.

## Test cases

6 test cases, including a leap-day pair that specifically exercises
completed-years-not-days/365 semantics:

1. **Exactly on the 66th birthday** → `eligible` (age route)
2. **One day before the 66th birthday** → `not_eligible`
3. **Leap-day birth (29 Feb 2000), day before the effective 66th birthday
   in a non-leap year** (28 Feb 2066 — 2066 has no 29 Feb) → `not_eligible`
   (still 65)
4. **Leap-day birth, effective 66th birthday reached** (1 Mar 2066 — the
   leap birthday "occurs" here in a non-leap year) → `eligible`
5. **Disability route** — 26-year-old applicant, no age eligibility, still
   qualifies → `eligible`
6. **Not ordinarily resident** — disqualifying regardless of age or
   disability → `not_eligible`

## Try it

### With the MCP (no sign-up needed for public rulesets)

```
> Is a 26-year-old UK resident with a disability certificate eligible for a
> concessionary travel pass?

Decision: eligible. Qualifies via the disability route (Section 5).
```

### Run the tests

```bash
uv run run_tests.py concessionary-travel-pass/
```

This calls the live public API and should pass all 6 scenarios without an
API key.

### Read the graph

```bash
uv run concessionary-travel-pass/scripts/graph_demo.py concessionary-travel-pass/
```

Fetches `GET /api/v1/public/rulesets/{ruleset_id}/graph` (public, no API
key required — same anonymous-access rule as `/decide` and `/schema`) and
prints every field/criterion/group/outcome node, then pulls out the
`age_route` criterion's raw compiled expression to show the `years_between`
operator in the AST it actually evaluates:

```json
{
  "type": "op", "operator": ">=",
  "args": [
    { "type": "op", "operator": "years_between", "args": [
      { "type": "field_ref", "key": "travel.applicant.date_of_birth" },
      { "type": "field_ref", "key": "travel.application.date" }
    ]},
    { "type": "const", "sort": "Int", "value": 66 }
  ]
}
```

Or with the CLI (`aethis-cli` v0.22.0+):

```bash
aethis rulesets graph concessionary-travel-pass:20260717-952f0a90
aethis rulesets graph concessionary-travel-pass:20260717-952f0a90 --mermaid
```

Or raw REST:

```bash
curl https://api.aethis.ai/api/v1/public/rulesets/concessionary-travel-pass:20260717-952f0a90/graph
```

### Walk the decision routes

```bash
uv run show_routes.py concessionary-travel-pass/
```

Feeds each test scenario's fields one at a time, following the engine's
optimal question order, and shows exactly where each route diverges (age
route vs disability route, and the residency short-circuit).

### With REST directly

```bash
curl -X POST https://api.aethis.ai/api/v1/public/decide \
  -H "Content-Type: application/json" \
  -d '{
    "ruleset_id": "aethis/concessionary-travel-pass",
    "field_values": {
      "travel.applicant.is_uk_resident": true,
      "travel.applicant.date_of_birth": "1960-03-15",
      "travel.application.date": "2026-03-15",
      "travel.applicant.has_disability_certificate": false
    }
  }'
```

(`/decide` accepts ISO date strings on DATE fields; the test-authoring
pipeline that produced `tests/scenarios.yaml` — `aethis generate`/`aethis
test` — expects the integer-ordinal form instead, so that file's dates are
written as ordinals with an ISO comment. Runtime callers should just use
ISO strings.)

## Fields

| Field | Type | Description |
|-------|------|--------------|
| `travel.applicant.is_uk_resident` | boolean | Ordinarily resident in the UK at the date of application |
| `travel.applicant.date_of_birth` | date | Applicant's date of birth |
| `travel.application.date` | date | Date of the application |
| `travel.applicant.has_disability_certificate` | boolean | Holds a valid qualifying disability certificate |

## Live references

- Rulebook: `aethis/concessionary-travel-pass`
- Ruleset: `concessionary-travel-pass:20260717-952f0a90`
- Engine: `aethis-core@0.45.2` (`years_between` shipped in `0.40.0`; `/graph` also `0.40.0`)
