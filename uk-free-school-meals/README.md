# UK Free School Meals — Worked Example

This example walks through the converged 2-term Aethis authoring workflow
(Rulebook + Ruleset, no Section/Project primitive) using UK Free School
Meals (FSM) eligibility as the domain.

It is designed to demonstrate **how multiple rulesets compose into a rulebook** —
the most important concept for anyone authoring multi-criteria eligibility systems.

> **Scope:** This is a dated, intentionally simplified Aethis composition demonstration, based on the demonstration corpus prepared in April 2026 and the rules published in July 2026. Its age, school-type, benefit and income assumptions are a fixed teaching model, not a complete statement of entitlement law. The exercises below extend that model; they are not an exhaustive list of legal omissions. Do not use the example to determine actual free school meal entitlement or as legal advice.
>
> **Citation review, 13 September 2026:** The cited school-attendance passage in Education Act 1996 s.512ZB(4A)(a) occurs unchanged in the current authority document. Other parts of that document were amended on 17 August 2026. Checking that passage verifies its text, not the legal completeness or currency of this model. Synthetic source files are Aethis-authored demonstration material, even where legacy filenames or headings resemble legislation.

---

## What this example covers

| Step | What you'll do | Tools |
|------|---------------|-------|
| **Inspect the sections** | Review the labelled source material, fields, and fixed test cases | `sections/*` |
| **Run the section tests** | Verify each ruleset against the live public API | `uv run run_tests.py ...` |
| **Evaluate the rulebook** | Run a decision against the composed public rulebook | `POST /api/v1/public/decide` with `rulebook_id` |

The three rulesets are independent and can be tested separately. The live
public rulebook composes their outcomes into one final decision.

---

## Section structure

The demonstration divides its fixed eligibility model into three sections:

```
Section A — child_eligibility
  Is the child aged 4–15 at a state-funded school in England?

Section B — household_qualifying_criteria
  Does the household receive a qualifying benefit or circumstance?
  (Universal Credit ≤ £7,400, Income Support, JSA, ESA, CTC, NASS,
   looked-after child, or care leaver)

Section C — universal_infant_fsm
  Is the child in Reception, Year 1, or Year 2?
  (No income test in this simplified model)

Outcome: A AND (B OR C)
```

Section A is a prerequisite gate for both routes. Sections B and C are alternative
routes — passing either is sufficient. A Year 1 child passes Section C regardless
of household income; a Year 6 child must pass Section B.

---

## Why three sections?

The demonstration models two routes with a shared prerequisite gate (Section A):

1. **Household route** (A + B): The model evaluates its fixed income and benefit assumptions.

2. **Infant route** (A + C): The model uses Reception–Year 2 without an income test. Section A still applies.

Modelling these as three rulesets makes the structure explicit and testable independently.
Each ruleset has its own source material, field spec, and fixed test cases.

---

## Directory layout

```
uk-free-school-meals/
├── README.md                          # This file
├── domain/hints.yaml                  # Cross-section guidance (applied to all sections)
├── rulebook.yaml                      # Composes all three rulesets + outcome logic (descriptive)
├── sources/                           # Demonstration source material (reference only)
│   ├── education_act_1996.md
│   ├── fsm_regulations_2014.md
│   └── children_families_act_2014.md
└── sections/
    ├── A_child_eligibility/
    │   ├── aethis.yaml                # section_id: child_eligibility
    │   ├── sources/                   # Citations uploaded for this section
    │   │   ├── education_act_1996_s512.md
    │   │   └── fsm_child_entitlement_demo.md
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
- **Alternative route without an income test**: Section C satisfies the model's B OR C disjunction; Section A still applies
- **Domain-level guidance with exact adherence**: Constrains section discovery
- **Threshold arithmetic**: Section B uses `≤ £7,400` comparison on an Int field
- **Enum fields**: `child.school_type` and `child.year_group`
- **Boolean OR logic within a section**: Multiple qualifying benefits in Section B

---

## Authority links and demonstration sources

- [Education Act 1996, Section 512](https://www.legislation.gov.uk/ukpga/1996/56/section/512)
- [The Education (Free School Meals) (England) Regulations 2014](https://www.legislation.gov.uk/uksi/2014/843/contents)
- [Children and Families Act 2014, Section 105](https://www.legislation.gov.uk/ukpga/2014/6/section/105)

---

## Exercises

These exercises address two simplifications in the dated demonstration corpus. They are authoring exercises, not a current legal checklist or a claim that all other entitlement conditions are implemented.

### Exercise 1 — Sixth-form pupils (ages 16–18)

**Model extension:** The demonstration corpus describes a sixth-form route and a Pension Credit criterion that the fixed rules do not implement. Review the actual authority text separately before adapting any example for real use.

The example's Section A currently gates on ages 4–15 only and Section B has no Pension Credit criterion.

**Your task:**
1. Extend Section A to also pass pupils aged 16–18 who are registered at a sixth form
2. Add a `household.receives_pension_credit_guarantee` boolean field to Section B
3. Add test cases covering a 17-year-old sixth-form pupil on Pension Credit (should pass) and a 17-year-old not in sixth form (should fail Section A)

---

### Exercise 2 — Child Tax Credit income threshold

**Model extension:** The demonstration corpus describes an additional Child Tax Credit income condition. The fixed model uses one boolean (`household.receives_child_tax_credit_only`) and does not implement that additional condition.

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

## Composition acceptance cases

[composition_cases.json](composition_cases.json) retains the three worked requests from the publishing script, plus missing-input and invalid-age controls. Its member names match that script's public composition. These five controls are separate from the 56 leaf scenarios. They describe the simplified teaching model; they do not establish current legal entitlement or prove that a matching immutable release is live.
