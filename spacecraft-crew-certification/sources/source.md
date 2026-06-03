# Spacecraft Crew Certification Act 2049

## Synthetic Legal Document

> This document is a synthetic statute modelled on the structure and language of
> UK primary legislation (cf. British Nationality Act 1981, Immigration Rules
> Appendix English Language). It serves as a demonstration of the Aethis
> eligibility engine.

---

## Part 1 — General Provisions

### Section 1: Short title and commencement

(1) This Act may be cited as the Spacecraft Crew Certification Act 2049.

(2) This Act comes into force on 1 January 2049.

### Section 2: Interpretation

In this Act—

- "the Authority" means the Galactic Aviation Authority;
- "approved provider" means a body approved under regulations made by the Authority;
- "orbital mission" means a mission involving one or more complete orbits of a celestial body;
- "suborbital mission" means a mission reaching space but not completing a full orbit;
- "lunar mission" means a mission to or around the Moon;
- "eligible species" means any species not excluded under Section 3(2);
- "approved propulsion type" means a propulsion system listed in Section 8(2).

---

## Part 2 — Eligibility Requirements

### Section 3: Species eligibility

(1) An applicant for crew certification must be of an eligible species.

(2) A Vogon national is not an eligible species for the purposes of this Act,
    by virtue of the Galactic Diplomatic Exclusion Treaty 2045.

(3) Where the applicant is a Vogon, the application must be refused without
    consideration of any other requirement under this Act.

---

### Section 4: Flight readiness

(1) The applicant must demonstrate flight readiness by satisfying all of
    the following conditions—

    (a) the applicant has accumulated not fewer than 500 flight hours; and

    (b) the applicant holds a valid pilot licence issued or recognised
        by the Authority.

---

### Section 5: Medical certification

(1) The applicant must hold a valid medical certificate obtained via one of
    the following routes—

    (a) **Route A:** an examination conducted by the Galactic Aviation Authority; or

    (b) **Route B:** a certification issued by an approved provider.

(2) Satisfaction of either route under subsection (1) is sufficient for the
    purposes of this section.

---

### Section 5A: Medical certificate validity period

(1) A medical certificate obtained under Section 5 is valid for a period
    of 730 days from the date of issue.

(2) The applicant's medical certificate must be valid at the date of
    application; that is, the application date must fall within 730 days
    of the certificate issue date.

---

### Section 6: Age exemption from flight readiness

(1) Subject to subsection (2), an applicant aged 60 or over is exempt
    from the flight readiness requirement in Section 4.

(2) The exemption under subsection (1) does not apply where the mission
    type is "orbital", unless subsection (3) applies.

(3) An applicant who has accumulated not fewer than 1000 flight hours
    is exempt from Section 4 regardless of mission type, notwithstanding
    subsection (2).

(4) For the avoidance of doubt—

    (a) an applicant aged 60 or over on a suborbital or lunar mission
        is exempt from Section 4 under subsection (1);

    (b) an applicant aged 60 or over on an orbital mission is NOT exempt
        from Section 4, unless the applicant has 1000+ flight hours
        under subsection (3);

    (c) an applicant aged 59 or under must always satisfy Section 4,
        regardless of flight hours.

---

### Section 7: Mission-specific requirements

(1) Where the mission type is "orbital"—

    (a) the applicant must hold a valid radiation protection certificate.

(2) Where the mission type is "suborbital" or "lunar", no radiation
    protection certificate is required.

---

### Section 8: Equipment compliance

(1) The vessel's propulsion system must be of an approved type.

(2) The approved propulsion types are—

    (a) Infinite Improbability Drive;

    (b) Bistromathics; and

    (c) Heart of Gold Special.

(3) A vessel using Conventional propulsion is not approved for crew
    certification missions.

---

### Section 9: Towel compliance

(1) The applicant must carry a towel at all times during the mission, in
    accordance with the Interstellar Hitchhiker Safety Regulations 2042.

---

## Part 3 — Determination of Outcome

### Section 10: Overall eligibility

(1) An applicant is eligible for crew certification if and only if all of
    the following conditions are met—

    (a) the applicant is of an eligible species (Section 3);

    (b) where the applicant is not exempt under Section 6, the applicant
        satisfies the flight readiness requirements (Section 4);

    (c) the applicant holds a valid medical certificate (Section 5) that
        is within its validity period (Section 5A);

    (d) where the mission type is orbital, the applicant holds a radiation
        protection certificate (Section 7);

    (e) the vessel's propulsion system is of an approved type (Section 8); and

    (f) the applicant carries a towel (Section 9).

---

## Appendix A — Input Fields

| Key | Type | Question | Allowed Values |
|-----|------|----------|----------------|
| `space.crew.species` | ENUM | What is the applicant's species? | Human, Vogon, Magrathean, Betelgeusian, Dolphin |
| `space.crew.flight_hours` | INT | How many flight hours has the applicant accumulated? | — |
| `space.crew.has_pilot_license` | BOOL | Does the applicant hold a valid pilot licence? | — |
| `space.crew.has_gaa_exam` | BOOL | Has the applicant passed a GAA medical examination? | — |
| `space.crew.has_approved_provider_cert` | BOOL | Does the applicant hold an approved provider medical certificate? | — |
| `space.crew.age` | INT | What is the applicant's age? | — |
| `space.medical.cert_valid` | BOOL | Is the medical certificate within 730 days of application? | — |
| `space.mission.type` | ENUM | What is the mission type? | orbital, suborbital, lunar |
| `space.crew.has_radiation_cert` | BOOL | Does the applicant hold a radiation protection certificate? | — |
| `space.vessel.propulsion_type` | ENUM | What type of propulsion system does the vessel use? | Infinite Improbability Drive, Bistromathics, Conventional, Heart of Gold Special |
| `space.crew.has_towel` | BOOL | Does the applicant carry a towel? | — |
