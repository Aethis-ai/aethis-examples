# UK Free School Meals — Worked Example

This example walks through the full three-phase Aethis authoring workflow using
UK Free School Meals (FSM) eligibility as the domain.

It is designed to demonstrate **how multiple sections compose into a rulebook** —
the most important concept for anyone authoring multi-criteria eligibility systems.

> **Disclaimer:** This example is for illustrative purposes only. While it references real UK legislation, the rules, field definitions, and test cases have been intentionally simplified for demonstration — two parts of the real law are omitted (see [Exercises](#exercises) below). This example should not be relied upon for legal advice or to determine actual free school meal entitlement. Always refer to the authoritative legislation and seek appropriate professional guidance.

---

## What this example covers

| Phase | What you'll do | Tools |
|-------|---------------|-------|
| **Phase 1 — Section discovery** | Discover and validate the three legislative sections | `aethis_discover_sections`, `aethis_validate_sections` |
| **Phase 2 — Field vocabulary** | Define the input fields for each section | `aethis_set_field_spec`, `aethis_discover_fields` |
| **Phase 3 — Rule generation** | Generate, test, and publish rules for each section | `aethis_generate_and_test`, `aethis_refine`, `aethis_publish` |

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

Modelling these as three sections makes the structure explicit and testable independently.
Each section has its own source legislation, field spec, test cases, and rule bundle.

---

## Directory layout

```
uk-free-school-meals/
├── README.md                          # This file
├── domain/hints.yaml                  # Cross-section guidance (applied to all sections)
├── rulebook.yaml                      # Composes all three bundles + outcome logic
└── sections/
    ├── A_child_eligibility/
    │   ├── aethis.yaml                # section_id: child_eligibility
    │   ├── sources/source.md          # Education Act 1996 §512
    │   ├── guidance/hints.yaml        # Section-specific guidance
    │   └── tests/scenarios.yaml       # 6 test cases
    ├── B_household_criteria/
    │   ├── aethis.yaml                # section_id: household_qualifying_criteria
    │   ├── sources/source.md          # Education (FSM) Regulations 2014
    │   ├── guidance/hints.yaml
    │   └── tests/scenarios.yaml       # 11 test cases
    └── C_universal_infant/
        ├── aethis.yaml                # section_id: universal_infant_fsm
        ├── sources/source.md          # Children and Families Act 2014 §105
        ├── guidance/hints.yaml
        └── tests/scenarios.yaml       # 6 test cases
```

---

## Authoring walkthrough

### Step 1 — Add domain-level guidance

Domain guidance applies to all sections. Add the hints from `domain/hints.yaml`
using `aethis_add_domain_guidance` with domain `uk_fsm` before starting any section.

The `adherence: exact` hints constrain the LLM to the correct section structure
and income field naming convention.

### Step 2 — Discover and validate sections

Run `aethis_discover_sections` with the three source documents concatenated.
Then run `aethis_validate_sections` against the expected section list:
`[child_eligibility, household_qualifying_criteria, universal_infant_fsm]`.

If sections are missing or incorrectly split, `aethis_refine_sections` with
guidance from `domain/hints.yaml` will correct them.

### Step 3 — Create projects (one per section)

Create three separate projects using `aethis_create_bundle`, one for each
`section_id`. Each project gets its own source document from `sources/source.md`
and its own test cases from `tests/scenarios.yaml`.

### Step 4 — Set field spec and discover fields (per section)

For each section, call `aethis_set_field_spec` with the expected fields, then
`aethis_discover_fields`. The auto-validation will flag any discrepancies.

**Section A fields:** `child.age` (Int), `child.school_type` (Enum)  
**Section B fields:** `household.receives_universal_credit` (Bool), `household.annual_net_earnings` (Int), `household.receives_income_support` (Bool), `household.receives_income_based_jsa` (Bool), `household.receives_income_related_esa` (Bool), `household.receives_child_tax_credit_only` (Bool), `household.receives_nass_support` (Bool), `child.is_looked_after` (Bool), `child.is_care_leaver` (Bool)  
**Section C fields:** `child.year_group` (Enum: reception, year_1, year_2, year_3, year_4, year_5, year_6, year_7_plus)

### Step 5 — Generate and test (per section)

Run `aethis_generate_and_test` for each section independently. Use `aethis_refine`
with feedback from the section's `guidance/hints.yaml` if tests fail.

The sections are independent — you can author them in parallel.

### Step 6 — Publish and compose

Once all three sections have published bundles (`aethis_publish`), the rulebook
in `rulebook.yaml` describes how they compose. The outcome logic `A AND (B OR C)`
is applied at the Rulebook level.

---

## Key concepts demonstrated

- **Multi-section composition**: Three independent bundles composed at the Rulebook level
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
