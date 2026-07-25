# Spacecraft Crew Certification Act 2049

A synthetic statute modelled on UK primary legislation, designed to exercise every pattern the Aethis eligibility engine supports.

## What this example covers

| Pattern | Section | Description |
|---------|---------|-------------|
| Disqualifying criterion | S.3 | Vogon species → immediate rejection, no further checks |
| Multi-field AND | S.4 | Flight hours ≥ 500 AND valid pilot licence |
| Multi-route OR | S.5 | GAA exam OR approved provider cert (either satisfies) |
| Date-bounded validity | S.5A | Medical cert must be within 730 days |
| Three-level exception chain | S.6 | Age 60+ exempt, except orbital, except 1000+ hours |
| Conditional requirement | S.7 | Orbital missions require radiation cert |
| Enum membership | S.8 | Propulsion must be an approved type |
| Simple boolean | S.9 | Must carry a towel |

## Test cases

5 test cases covering:

1. **Vogon crew member** — disqualifying species → `not_eligible`
2. **No towel** — equipment violation → `not_eligible`
3. **Orbital without radiation cert** — conditional requirement fails → `not_eligible`
4. **Full compliance** — all requirements met → `eligible`
5. **Age exemption** — senior crew (65), no flight hours/licence → `eligible`

## Try it

### With the MCP (no sign-up needed for public rulesets)

```
> Is a Vogon eligible for crew certification?

Decision: not eligible. No more questions needed.
```

### Run the tests

```bash
uv run run_tests.py spacecraft-crew-certification/
```

This calls the live public API and should pass all 5 scenarios without an API key.

### With REST

```bash
curl -X POST https://api.aethis.ai/api/v1/public/decide \
  -H "Content-Type: application/json" \
  -d '{"ruleset_id": "aethis/spacecraft-crew-certification", "field_values": {"space.crew.species": "Vogon"}}'
```

### Why single-ruleset?

The statute is short enough to live in one public ruleset. Multi-section
examples (see [`uk-free-school-meals/`](../uk-free-school-meals/)) split
the source material into independent rulesets and compose their outcomes
at the rulebook level.

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `space.crew.species` | enum | Human, Vogon, Magrathean, Betelgeusian, Dolphin |
| `space.crew.flight_hours` | integer | Accumulated flight hours |
| `space.crew.has_pilot_license` | boolean | Valid pilot licence |
| `space.crew.has_gaa_exam` | boolean | GAA medical examination passed |
| `space.crew.has_approved_provider_cert` | boolean | Approved provider certificate |
| `space.crew.age` | integer | Applicant age |
| `space.medical.cert_valid` | boolean | Medical cert within 730 days |
| `space.mission.type` | enum | orbital, suborbital, lunar |
| `space.crew.has_radiation_cert` | boolean | Radiation protection certificate |
| `space.vessel.propulsion_type` | enum | Infinite Improbability Drive, Bistromathics, Conventional, Heart of Gold Special |
| `space.crew.has_towel` | boolean | Carries a towel |
| `pilot_licence.issuing_status` | enum | issued_by_authority, recognised_by_authority, not_issued_or_recognised |
| `pilot_licence.expiry_date` | date | Pilot licence expiry date |
| `medical_certificate.issue_date` | date | Medical certificate issue date |
| `radiation_certificate.expiry_date` | date | Radiation protection certificate expiry date |
| `application.date` | date | Application date |
