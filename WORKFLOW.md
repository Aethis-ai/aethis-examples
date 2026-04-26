# Rule Authoring Workflow

How to author, test, and refine eligibility rules using the Aethis platform.

## Overview

```
Source legislation → SME guidance → Rule generation → Testing → Refinement → Publication
```

The system uses a test-driven approach: you define the expected outcomes first,
then generate rules that satisfy them. The authoring agent iterates until all
tests pass, and guidance hints accumulate to improve future runs.

## Step 1: Prepare source material

Create three files in your project directory:

```
my-rules/
├── aethis.yaml              # Project name and config
├── sources/
│   └── source.md            # The legislation, policy, or specification
├── guidance/
│   └── hints.yaml           # SME guidance hints
└── tests/
    └── scenarios.yaml       # Golden test cases with expected outcomes
```

### Source material (`sources/source.md`)

The raw legislation or policy text. Write it as you would a legal document —
clauses, subclauses, cross-references. No annotations or pattern hints needed.

### Guidance hints (`guidance/hints.yaml`)

Subject matter expertise that helps the rule generator understand the domain.
Two types of hint:

**Data contract** — defines the fields used to capture applicant/claim data:

```yaml
hints:
  - >
    The following fields capture applicant data for credit pre-qualification.
    These field keys and types define the data contract:
    credit.has_adverse_history (boolean),
    credit.employment_status (enum: employed, self_employed, retired, unemployed),
    credit.gross_annual_income (integer, GBP),
    ...
```

**Domain knowledge** — explains how rules interact:

```yaml
  - >
    Any adverse credit history is an absolute disqualification. No other
    factor can override this — the application must be refused immediately.

  - >
    The income requirement can be met by either sole income (at least £15,000)
    or combined income with a joint applicant (at least £20,000).
```

Guidance hints should be written in natural language by a subject matter
expert. They describe *what* the rules should do, not *how* to encode them.

### Test cases (`tests/scenarios.yaml`)

Golden test cases that define the expected behaviour:

```yaml
tests:
  - name: "Adverse credit — immediate decline"
    inputs:
      credit.has_adverse_history: true
    expect:
      outcome: not_eligible

  - name: "Good applicant — approved"
    inputs:
      credit.has_adverse_history: false
      credit.employment_status: employed
      credit.gross_annual_income: 35000
      ...
    expect:
      outcome: eligible
```

## Step 2: Generate rules

```bash
aethis generate --poll
```

The authoring agent:
1. Reads the source legislation
2. Loads SME guidance hints
3. Generates rule code
4. Validates syntax
5. Compiles to constraints
6. Runs all test cases
7. Fixes failures and iterates
8. Stops when all tests pass (or reports the best result)

A guidance snapshot is created at generation time, capturing exactly which
hints were active. This snapshot is stored with the bundle for auditability.

## Step 3: Review results

If all tests pass, the rules are ready to publish:

```bash
aethis publish
```

If some tests fail, review the failures and refine the guidance.

## Step 4: Refine guidance

The authoring agent may generate its own guidance hints during authoring.
These are marked with `source: agent` to distinguish them from human SME hints.

To review all hints (human + agent-generated):

```bash
aethis guidance list
```

To export hints back to a YAML file for review:

```bash
aethis guidance export > guidance/hints_v2.yaml
```

The exported YAML includes source attribution:

```yaml
hints:
  - text: "Any adverse credit history is an absolute disqualification."
    source: human

  - text: "The enhanced cover threshold depends on who installed the component."
    source: agent
```

Review the agent-generated hints. Edit or remove any that are incorrect,
then re-import:

```bash
aethis guidance import guidance/hints_v2.yaml
```

Regenerate rules with the improved guidance:

```bash
aethis generate --poll
```

## Step 5: Audit trail

Every published bundle references:
- The source legislation it was generated from
- The guidance snapshot (frozen set of hints at generation time)
- The test cases it was validated against
- Provenance tracing each rule back to source clauses

Hints are immutable — editing a hint creates a new version, the original is
preserved. You can always reconstruct exactly what guidance was active when
any bundle was generated.

## Tips

- **Start with the data contract** — define fields and types first, domain
  knowledge hints second. The field definitions are the most important hint.
- **Write tests before guidance** — the tests define what "correct" means.
  Guidance helps the agent get there faster, but tests are the authority.
- **Let the agent learn** — agent-generated hints often capture patterns
  that humans miss. Review them, but don't dismiss them automatically.
- **Version your YAML files** — commit `hints.yaml` to version control.
  When making significant changes, save as `hints_v2.yaml` etc.
