# Consumer Credit Pre-Qualification Rules 2025

## Synthetic Regulation — Controlled Test Fixture

> This document is a synthetic regulation modelled on UK FCA MCOB (Mortgages and
> Home Finance: Conduct of Business) rules and US CFPB ability-to-repay
> requirements. It is designed to exercise eligibility engine patterns in a
> lending context. It does not reflect any real lender's criteria.

> **Named Product:** Meridian Personal Credit Facility (fictional)

---

## Part 1 — General Provisions

### Section 1: Title and applicability

(1) These rules may be cited as the Consumer Credit Pre-Qualification Rules 2025.

(2) These rules apply to all applications for the Meridian Personal Credit
    Facility, whether secured or unsecured.

### Section 2: Interpretation

In these rules—

- "applicant" means the primary applicant for the credit facility;
- "joint applicant" means a second applicant whose income may be considered
  alongside the primary applicant;
- "gross annual income" means the applicant's total annual income before tax
  and deductions;
- "monthly debt obligation" means the total of all existing monthly debt
  payments including credit cards, loans, and finance agreements;
- "debt-to-income ratio" (DTI) means monthly debt obligation divided by
  gross monthly income (gross annual income / 12), expressed as a percentage;
- "credit score band" means the applicant's credit rating category as
  determined by a recognised credit reference agency;
- "secured facility" means a credit facility secured against residential property;
- "unsecured facility" means a credit facility with no security;
- "loan-to-value ratio" (LTV) means the loan amount divided by the property
  value, expressed as a percentage;
- "stress-tested rate" means the lender's standard variable rate plus a
  stress buffer of 3 percentage points;
- "existing customer" means an applicant who has held a Meridian account in
  good standing for not less than 24 months.

---

## Part 2 — Eligibility Determination

### Section 3: Adverse credit history

(1) An applicant with an adverse credit history must be refused without
    consideration of any other requirement under these rules.

(2) For the purposes of this section, adverse credit history means any of
    the following recorded within the preceding 6 years—

    (a) a County Court Judgment (CCJ) or equivalent;
    (b) an Individual Voluntary Arrangement (IVA);
    (c) bankruptcy or sequestration;
    (d) a default on any credit agreement.

---

### Section 4: Employment status

(1) The applicant must be in one of the following employment categories—

    (a) employed (full-time or part-time);
    (b) self-employed (trading not less than 2 years);
    (c) retired (receiving pension income).

(2) An applicant who is unemployed, a student, or on a zero-hours contract
    is not eligible for the credit facility.

---

### Section 5: Income threshold

(1) The applicant must demonstrate sufficient income by satisfying one of
    the following routes—

    (a) **Route A (sole income):** the applicant's gross annual income is
        not less than GBP 15,000; or

    (b) **Route B (joint income):** the combined gross annual income of the
        applicant and a joint applicant is not less than GBP 20,000.

(2) Satisfaction of either route under subsection (1) is sufficient for the
    purposes of this section.

---

### Section 6: Debt-to-income ratio

(1) The applicant's debt-to-income ratio must not exceed 45%.

(2) The debt-to-income ratio is calculated as—

        DTI = (monthly_debt_obligation / (gross_annual_income / 12)) × 100

---

### Section 7: Credit score requirement

(1) The applicant's credit score band must meet the minimum requirement
    for the product type—

    (a) for a **secured** facility: the credit score band must be "fair",
        "good", or "excellent";

    (b) for an **unsecured** facility: the credit score band must be "good"
        or "excellent".

(2) An applicant with a credit score band of "poor" or "very_poor" is not
    eligible for any product type.

---

### Section 8: Loan-to-value ratio (secured facilities only)

(1) Where the facility is a secured facility, the loan-to-value ratio must
    not exceed 85%.

(2) The loan-to-value ratio is calculated as—

        LTV = (loan_amount / property_value) × 100

(3) This section does not apply to unsecured facilities.

---

### Section 9: Affordability stress test

(1) The applicant must demonstrate that monthly repayments remain affordable
    under a stressed interest rate scenario.

(2) The stressed monthly payment is calculated using the stress-tested rate
    (standard variable rate plus 3 percentage points) applied to the full
    loan amount over the full loan term.

(3) The stressed monthly payment must not exceed 35% of the applicant's
    gross monthly income.

---

### Section 10: Existing customer exception

(1) An existing customer (as defined in Section 2) is exempt from the
    requirements of Section 6 (debt-to-income ratio).

(2) All other requirements under these rules continue to apply to existing
    customers.

(3) For the purposes of this section, "good standing" means no missed
    payments and no adverse events during the 24-month qualifying period.

---

## Appendix A — Input Fields

| Key | Sort | Question | Allowed Values |
|-----|------|----------|----------------|
| `credit.has_adverse_history` | BOOL | Does the applicant have any adverse credit history (CCJ, IVA, bankruptcy, default) in the last 6 years? | — |
| `credit.employment_status` | ENUM | What is the applicant's employment status? | employed, self_employed, retired, unemployed, student |
| `credit.gross_annual_income` | INT | What is the applicant's gross annual income in GBP? | — |
| `credit.has_joint_applicant` | BOOL | Is there a joint applicant? | — |
| `credit.joint_annual_income` | INT | What is the joint applicant's gross annual income in GBP? | — |
| `credit.dti_percent` | INT | What is the applicant's debt-to-income ratio as a percentage? | — |
| `credit.credit_score_band` | ENUM | What is the applicant's credit score band? | excellent, good, fair, poor, very_poor |
| `credit.product_type` | ENUM | Is the facility secured or unsecured? | secured, unsecured |
| `credit.ltv_percent` | INT | What is the loan-to-value ratio as a percentage? (Secured only) | — |
| `credit.stress_test_passed` | BOOL | Does the applicant pass the affordability stress test? | — |
| `credit.is_existing_customer` | BOOL | Is the applicant an existing Meridian customer (24+ months in good standing)? | — |

## Appendix B — Groups and Outcome Logic

| Group Name | Criteria | Section |
|------------|----------|---------|
| `adverse_history_check` | has_adverse_history == false | S.3 |
| `employment_check` | employment_status IN [employed, self_employed, retired] | S.4 |
| `income_check` | Route A: income >= 15000 OR Route B: joint income >= 20000 | S.5 |
| `dti_check` | dti_percent <= 45 (bypassed for existing customers) | S.6, S.10 |
| `credit_score_check` | Product-conditional: secured allows fair+, unsecured requires good+ | S.7 |
| `ltv_check` | IF secured THEN ltv_percent <= 85 | S.8 |
| `stress_test_check` | stress_test_passed == true | S.9 |

> **Outcome logic:** All groups must be satisfied (AND). Early termination on adverse history.
