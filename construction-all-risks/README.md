# CAR Policy Defect Exclusion Endorsement 2025

A synthetic insurance endorsement modelled on London market Construction All Risks (CAR) policy wordings, specifically the DE3/DE5 defect exclusion clause structure and LEG3/06 endorsement patterns used for major infrastructure projects.

## What this example covers

| Pattern | Clause | Description |
|---------|--------|-------------|
| Multi-field AND | Cl.4 | Physical loss AND defective component identified |
| Multi-route OR | Cl.7 | Carve-back via consequence of failure OR non-access damage |
| Three-level exception chain | Cl.9 | Access damage excluded, except enhanced cover, except design defects, except pioneer projects |
| Nested IMPLIES | Cl.10 | Existing structures require JCT-compliant contract |
| Early termination | Cl.3 | Loss outside policy period = immediate rejection |
| ENUM + IN operator | Cl.5 | Property must be an approved insured category |
| Pre-computed BOOL | Cl.11 | Notification within 30 days |
| Override (exception to exception) | Cl.9(3) | Pioneer project (>=500M) overrides design defect exclusion |

## Test cases

8 test cases covering the full exception chain:

1. **Rectification claim** — absolute exclusion, no override possible
2. **Consequential damage** — carve-back applies (LEG3 route)
3. **Access damage (standard project)** — re-excluded after carve-back
4. **Access damage (enhanced project >=100M)** — reinstated by enhanced cover
5. **Design defect (enhanced project)** — enhanced cover does not apply
6. **Design defect (pioneer project >=500M)** — pioneer override reinstates
7. **Plant equipment** — excluded insured category
8. **Late notification** — outside notification period

## Try it

### With the CLI

```bash
cd construction-all-risks
aethis generate --poll
aethis test
aethis publish
aethis decide -i '{"car.claim.is_rectification": true}'
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `car.policy.period_valid` | boolean | Loss within policy period |
| `car.property.category` | enum | permanent_works, temporary_works, plant_equipment, existing_structures, materials_on_site |
| `car.loss.is_physical` | boolean | Physical loss or damage occurred |
| `car.component.is_defective` | boolean | Defective component identified |
| `car.defect.origin` | enum | design, specification, materials, workmanship, none |
| `car.claim.is_rectification` | boolean | Claim is for rectification cost |
| `car.claim.is_access_damage` | boolean | Damage caused to gain access to defective component |
| `car.damage.consequence_of_failure` | boolean | Damage arose from defective component failing |
| `car.project.value_millions_gbp` | integer | Total insured project value (GBP millions) |
| `car.notification.within_period` | boolean | Notified within 30 days |
| `car.contract.jct_compliant` | boolean | JCT-compliant contract in place |
