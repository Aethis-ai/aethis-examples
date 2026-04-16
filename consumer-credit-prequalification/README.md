# Consumer Credit Pre-Qualification Rules 2025

A synthetic lending regulation modelled on UK FCA MCOB and US CFPB ability-to-repay rules. Exercises eligibility engine patterns in a consumer finance context — pure boolean/threshold logic with no discretion.

## Why this example matters

LLMs consistently fail on lending eligibility because they can't reliably track:
- Absolute disqualifications that override everything else
- Product-specific thresholds (secured vs unsecured require different credit scores)
- Customer status exceptions (existing customers bypass DTI checks)
- The interaction between joint income routes and individual affordability tests

A wrong answer in lending isn't a UX bug — it's a regulatory violation.

## What this example covers

| Pattern | Section | Description |
|---------|---------|-------------|
| Early termination | S.3 | Adverse credit history = immediate decline, no further checks |
| Enum membership | S.4 | Employment must be employed, self-employed, or retired |
| Multi-route OR | S.5 | Sole income ≥ 15K OR joint income ≥ 20K |
| Numeric threshold | S.6 | Debt-to-income ratio ≤ 45% |
| Product-conditional enum | S.7 | Secured allows "fair"+, unsecured requires "good"+ |
| Conditional requirement | S.8 | LTV ≤ 85% applies only to secured facilities |
| Nested numeric | S.9 | Stress-tested affordability check |
| Exception bypass | S.10 | Existing customers exempt from DTI check |

## Test cases

8 test cases covering the full decision tree:

1. **Adverse credit** — immediate decline (early termination)
2. **Unemployed** — excluded employment status
3. **Good standalone applicant** — all checks pass, approved
4. **Joint application rescues low income** — Route B (multi-route OR)
5. **High DTI, existing customer** — exemption bypasses DTI check
6. **Stress test failure** — affordability under stressed rates fails
7. **Secured loan, high LTV** — loan-to-value exceeds 85%
8. **Fair credit on unsecured** — needs "good" or better for unsecured

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `credit.has_adverse_history` | boolean | CCJ, IVA, bankruptcy, or default in last 6 years |
| `credit.employment_status` | enum | employed, self_employed, retired, unemployed, student |
| `credit.gross_annual_income` | integer | Gross annual income (GBP) |
| `credit.has_joint_applicant` | boolean | Joint applicant present |
| `credit.joint_annual_income` | integer | Joint applicant's gross annual income (GBP) |
| `credit.dti_percent` | integer | Debt-to-income ratio (%) |
| `credit.credit_score_band` | enum | excellent, good, fair, poor, very_poor |
| `credit.product_type` | enum | secured, unsecured |
| `credit.ltv_percent` | integer | Loan-to-value ratio (%) — secured only |
| `credit.stress_test_passed` | boolean | Passes affordability stress test |
| `credit.is_existing_customer` | boolean | Meridian customer 24+ months, good standing |
