# Concessionary Travel Pass Act 2051

## Synthetic Legal Document

> This document is a synthetic statute modelled on the structure and language of
> UK primary legislation (cf. the Transport Act 2000, Part II — Travel
> Concessions). It serves as a demonstration of the Aethis eligibility engine,
> in particular its handling of **age calculated from a date of birth**.

---

## Part 1 — General Provisions

### Section 1: Short title and commencement

(1) This Act may be cited as the Concessionary Travel Pass Act 2051.

(2) This Act comes into force on 1 January 2051.

### Section 2: Interpretation

In this Act—

- "the Authority" means the Transport Concessions Authority;
- "pass age" means 66 years, reckoned as the number of **completed whole
  years** between the applicant's date of birth and the date of the
  application — that is, whether the applicant's 66th birthday has been
  reached on or before the application date, not merely whether the
  calendar year of birth is 66 or more years before the calendar year of
  application;
- "qualifying disability certificate" means a certificate of eligibility
  issued by the Authority under regulations made pursuant to Section 5;
- "ordinarily resident" has its ordinary meaning at common law.

---

## Part 2 — Eligibility Requirements

### Section 3: Residency requirement

(1) An applicant for a concessionary travel pass must be ordinarily
    resident in the United Kingdom at the date of application.

(2) An applicant who is not ordinarily resident in the United Kingdom is
    not eligible for a pass under this Act, regardless of whether the
    applicant satisfies any other requirement.

---

### Section 4: The age route

(1) An applicant qualifies for a pass via the age route where the
    applicant has reached pass age at the date of application.

(2) For the avoidance of doubt, pass age is reached on the applicant's
    66th birthday, determined by counting the number of completed whole
    years from the applicant's date of birth to the date of application —
    the applicant is treated as 65 on the day before that birthday and 66
    from that birthday onward, in every case, including where the
    applicant's date of birth falls on 29 February.

(3) An applicant who has not reached pass age does not qualify via the
    age route, but may still qualify via the disability route under
    Section 5.

---

### Section 5: The disability route

(1) An applicant who holds a valid qualifying disability certificate
    qualifies for a pass via the disability route, irrespective of the
    applicant's age.

(2) The disability route and the age route are independent; an applicant
    who satisfies either route (or both) has satisfied the eligibility
    requirement in Section 6(1)(b).

---

## Part 3 — Determination of Outcome

### Section 6: Overall eligibility

(1) An applicant is eligible for a concessionary travel pass if and only
    if both of the following conditions are met—

    (a) the applicant satisfies the residency requirement (Section 3);
        and

    (b) the applicant qualifies via the age route (Section 4) or the
        disability route (Section 5), or both.

---

## Appendix A — Input Fields

| Key | Type | Question | Allowed Values |
|-----|------|----------|----------------|
| `travel.applicant.is_uk_resident` | BOOL | Is the applicant ordinarily resident in the United Kingdom at the date of application? | — |
| `travel.applicant.date_of_birth` | DATE | What is the applicant's date of birth? | — |
| `travel.application.date` | DATE | What is the date of the application? | — |
| `travel.applicant.has_disability_certificate` | BOOL | Does the applicant hold a valid qualifying disability certificate issued by the Authority? | — |
