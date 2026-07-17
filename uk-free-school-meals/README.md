# UK Free School Meals — Worked Example

This example walks through the converged 2-term Aethis authoring workflow
(Rulebook + Ruleset, no Section/Project primitive) using UK Free School
Meals (FSM) eligibility as the domain.

It is designed to demonstrate **how multiple rulesets compose into a rulebook** —
the most important concept for anyone authoring multi-criteria eligibility systems.

> **Disclaimer:** This example is for illustrative purposes only. While it references real UK legislation, the rules, field definitions, and test cases have been intentionally simplified for demonstration — two parts of the real law are omitted (see [Exercises](#exercises) below). This example should not be relied upon for legal advice or to determine actual free school meal entitlement. Always refer to the authoritative legislation and seek appropriate professional guidance.

---

## What this example covers

| Step | What you'll do | Tools |
|------|---------------|-------|
| **Inspect the sections** | Review the source legislation, fields, and test cases for each ruleset | `sections/*` |
| **Run the section tests** | Verify each ruleset against the live public API | `uv run run_tests.py ...` |
| **Evaluate the rulebook** | Run a decision against the composed public rulebook | `POST /api/v1/public/decide` with `rulebook_id` |

The three rulesets are independent and can be tested separately. The live
public rulebook composes their outcomes into one final decision.

---

## Section structure

UK Free School Meals eligibility has three distinct sections:

```
Section A — child_eligibility
  Is the child aged 4–15 at a state-funded school in England?

Section B — household_qualifying_criteria
  Does the household receive a qualifying benefit or circumstance?
  (Universal Credit ≤ £7,400, Income Support, JSA, ESA, CTC, NASS,
   looked-after child, or care leaver)

Section C — universal_infant_fsm
  Is the child in Reception, Year 1, or Year 2?
  (No income test — automatic entitlement under the Children and Families Act 2014)

Outcome: A AND (B OR C)
```

Section A is a prerequisite gate for both routes. Sections B and C are alternative
routes — passing either is sufficient. A Year 1 child passes Section C regardless
of household income; a Year 6 child must pass Section B.

---

## Why three sections?

The legislation creates two distinct entitlements that share a common eligibility
gate (Section A):

1. **Means-tested entitlement** (A + B): The classic free school meals route,
   dating from the Education Act 1996. Income and benefit criteria determine eligibility.

2. **Universal Infant entitlement** (A + C): Introduced by the Children and Families
   Act 2014. All Reception–Year 2 children qualify regardless of household income.

Modelling these as three rulesets makes the structure explicit and testable independently.
Each ruleset has its own source legislation, field spec, and test cases.

---

## Directory layout

```
uk-free-school-meals/
├── README.md                          # This file
├── domain/hints.yaml                  # Cross-section guidance (applied to all sections)
├── rulebook.yaml                      # Composes all three rulesets + outcome logic (descriptive)
├── sources/                           # Full statute texts (reference only)
│   ├── education_act_1996.md
│   ├── fsm_regulations_2014.md
│   └── children_families_act_2014.md
└── sections/
    ├── A_child_eligibility/
    │   ├── aethis.yaml                # section_id: child_eligibility
    │   ├── sources/                   # Citations uploaded for this section
    │   │   ├── education_act_1996_s512.md
    │   │   └── fsm_regulations_2014_reg3.md
    │   ├── guidance/hints.yaml        # Section-specific guidance
    │   └── tests/scenarios.yaml       # 6 test cases
    ├── B_household_criteria/
    │   ├── aethis.yaml                # section_id: household_qualifying_criteria
    │   ├── sources/
    │   │   ├── fsm_regulations_2014_reg4.md
    │   │   └── fsm_regulations_2014_reg4a.md
    │   ├── guidance/hints.yaml
    │   └── tests/scenarios.yaml       # 11 test cases
    └── C_universal_infant/
        ├── aethis.yaml                # section_id: universal_infant_fsm
        ├── sources/
        │   ├── children_families_act_2014_s105.md
        │   └── fsm_regulations_2014_reg5.md
        ├── guidance/hints.yaml
        └── tests/scenarios.yaml       # 6 test cases
```

---

## Try it

The public catalog already has this example live as `aethis/uk-fsm`. You can
run the three section-level rulesets anonymously, then evaluate the composed
rulebook with an API key.

### Step 1 — Run the section tests

```bash
uv run run_tests.py uk-free-school-meals/sections/A_child_eligibility/
uv run run_tests.py uk-free-school-meals/sections/B_household_criteria/
uv run run_tests.py uk-free-school-meals/sections/C_universal_infant/
```

Expected result: all 23 section scenarios pass against the live API.

### Step 2 — Understand the composition

The rulebook composes the three section outcomes as:

```text
child_eligibility AND (household_criteria OR universal_infant)
```

Section A is the shared gate. Section B is the means-tested route. Section C is
the universal infant route.

### Step 3 — Evaluate the composed rulebook

Decide against the composed rulebook by passing `rulebook_id` to the
universal `/decide` endpoint. **Rulebook evaluation requires an API key**
(the engine returns 401 for anonymous rulebook decide; anonymous access is
reserved for individual ruleset decisions). Sign up at `https://aethis.ai`.

The public rulebook contains these named rulesets:

| Section dir | Ruleset name |
|---|---|
| `A_child_eligibility` | `child_eligibility` |
| `B_household_criteria` | `household_criteria` |
| `C_universal_infant` | `universal_infant` |

The three rulesets are independently testable and share fields through the
single case record sent to `/decide`.

- **child_eligibility fields:** `child.age` (Int), `child.school_type` (Enum)
- **household_criteria fields:** `household.receives_universal_credit` (Bool), `household.annual_net_earnings` (Int), `household.receives_income_support` (Bool), `household.receives_income_based_jsa` (Bool), `household.receives_income_related_esa` (Bool), `household.receives_child_tax_credit_only` (Bool), `household.receives_nass_support` (Bool), `child.is_looked_after` (Bool), `child.is_care_leaver` (Bool)
- **universal_infant fields:** `child.year_group` (Enum: reception, year_1, year_2, year_3, year_4, year_5, year_6, year_7_plus)

```bash
curl -X POST https://api.aethis.ai/api/v1/public/decide \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AETHIS_API_KEY" \
  -d '{
    "rulebook_id": "aethis/uk-fsm",
    "field_values": {
      "child.age": 5,
      "child.school_type": "state_funded",
      "child.year_group": "year_1",
      "household.receives_universal_credit": false,
      "household.annual_net_earnings": 60000,
      "household.receives_income_support": false,
      "household.receives_income_based_jsa": false,
      "household.receives_income_related_esa": false,
      "household.receives_child_tax_credit_only": false,
      "household.receives_nass_support": false,
      "child.is_looked_after": false,
      "child.is_care_leaver": false
    }
  }'
```

A Year-1 child in a state-funded school passes through the universal infant
route (C) regardless of household income. A Year-6 child needs the means-test
route (B). Either route satisfies the disjunction, gated by section A.

---

## Key concepts demonstrated

- **Multi-ruleset composition**: Three independent rulesets composed at the Rulebook level
- **OR logic across sections**: Sections B and C are alternative routes
- **Automatic entitlement override**: Section C has no income test
- **Domain-level guidance with exact adherence**: Constrains section discovery
- **Threshold arithmetic**: Section B uses `≤ £7,400` comparison on an Int field
- **Enum fields**: `child.school_type` and `child.year_group`
- **Boolean OR logic within a section**: Multiple qualifying benefits in Section B

---

## Source legislation

- [Education Act 1996, Section 512](https://www.legislation.gov.uk/ukpga/1996/56/section/512)
- [The Education (Free School Meals) (England) Regulations 2014](https://www.legislation.gov.uk/uksi/2014/843/contents)
- [Children and Families Act 2014, Section 105](https://www.legislation.gov.uk/ukpga/2014/6/section/105)

---

## Exercises

Two parts of the real legislation are intentionally omitted to keep the example focused. They make good authoring exercises once you've worked through the main walkthrough.

### Exercise 1 — Sixth-form pupils (ages 16–18)

**What's missing:** [Regulation 3](https://www.legislation.gov.uk/uksi/2014/843/regulation/3) covers not just under-16s but also "relevant sixth-form pupils" aged 16–18. [Regulation 4(g)](https://www.legislation.gov.uk/uksi/2014/843/regulation/4) adds a qualifying benefit that only applies to this group: the **Guarantee Credit element of Pension Credit** under the State Pension Credit Act 2002.

The example's Section A currently gates on ages 4–15 only and Section B has no Pension Credit criterion.

**Your task:**
1. Extend Section A to also pass pupils aged 16–18 who are registered at a sixth form
2. Add a `household.receives_pension_credit_guarantee` boolean field to Section B
3. Add test cases covering a 17-year-old sixth-form pupil on Pension Credit (should pass) and a 17-year-old not in sixth form (should fail Section A)

---

### Exercise 2 — Child Tax Credit income threshold

**What's missing:** The example models Child Tax Credit as a single boolean field (`household.receives_child_tax_credit_only`), which captures the "not entitled to Working Tax Credit" condition but silently drops the second condition in [Regulation 4(e)](https://www.legislation.gov.uk/uksi/2014/843/regulation/4): the household's **annual gross income must not exceed £16,190** (as calculated by HMRC).

A family receiving CTC with no WTC entitlement but an income of £20,000 would incorrectly pass Section B as currently modelled.

**Your task:**
1. Split `household.receives_child_tax_credit_only` into two fields: `household.receives_child_tax_credit` (Bool) and `household.annual_gross_income_hmrc` (Int)
2. Update the Section B rules so CTC only qualifies when both conditions are met: receiving CTC with no WTC entitlement, and annual gross income ≤ £16,190
3. Add test cases for: CTC + income £14,000 (should pass), CTC + income £18,000 (should fail on this criterion), and a household on both CTC and WTC (should fail)

---

## Three-tier example roadmap

This is the **hard tier** example. Two simpler tiers are planned:

| Tier | Scope | Status |
|------|-------|--------|
| **Hard** (this example) | 3 sections, income arithmetic, benefit enums, UIFSM override | Ready for authoring |
| **Medium** | 1–2 sections, 2 eligibility routes, 1 date comparison | Planned |
| **Easy** | 1 section, 1 criterion, 1 field | Planned |
