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

### With the MCP (no sign-up needed for public rulebooks)

```
> Is a Vogon eligible for crew certification?

Decision: not eligible. No more questions needed.
```

### With the CLI (converged 2-term workflow)

The example is structured as a Rulebook with a single Ruleset. The
flow shown below is the end-to-end CLI surface for the 2-term
authoring model — exercised by `scripts/publish-rulebook.sh`.

```bash
cd spacecraft-crew-certification

# 1. Create the Rulebook (top-level container for the form / decision)
aethis rulebooks create "Spacecraft Crew Certification" \
    --domain spacecraft \
    --slug aethis/spacecraft-crew-certification

# 2. Author the ruleset content via the project pipeline
aethis generate --poll
aethis test

# 3. Publish INTO the rulebook — stamps the bundle with rulebook_id +
#    ruleset_name and lands it in state=testing (not status=active)
aethis publish --rulebook aethis/spacecraft-crew-certification \
               --ruleset-name crew_certification

# 4. Promote to live — atomic; auto-cuts a new Rulebook version
aethis rulesets promote-to-live aethis/spacecraft-crew-certification \
    crew_certification <ruleset_id-from-step-3>

# 5. Decide against the live rulebook
aethis rulebooks decide aethis/spacecraft-crew-certification \
    -i '{"space.crew.species": "Vogon"}'
```

Or run the whole thing in one shot:

```bash
./scripts/publish-rulebook.sh
```

### Inspecting state

```bash
aethis rulebooks show aethis/spacecraft-crew-certification
aethis rulebooks versions aethis/spacecraft-crew-certification
aethis rulesets list aethis/spacecraft-crew-certification
aethis rulesets show aethis/spacecraft-crew-certification crew_certification
```

### Why single-ruleset?

The statute is short enough to live in one named ruleset. Multi-section
examples (see [`uk-free-school-meals/`](../uk-free-school-meals/)) split
across multiple rulesets composed via the Rulebook's `outcome_logic`
expression. The single-ruleset case here is the simplest end-to-end
exercise of the CLI surface — it's the smoke test that proves the new
authoring workflow before introducing the multi-ruleset composition
story.

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
