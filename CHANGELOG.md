# Changelog

## 0.2.6 — 2026-09-24

- Repins the spacecraft example to v8 (`spacecraft-crew-certification:20260924-715ae5c9`), republished against the restored Section 6(4)(c). Under the restored text, 1,000+ flight hours exempts an applicant from Section 4 at any age, so the "age 30, 1,200 hours, no licence" test case now expects `eligible`. The rule logic is the same as before 0.2.3.
- Keeps the superseded text of the Act under `spacecraft-crew-certification/sources/retained/`, named by its digest. The quickstart's recorded responses cite that earlier text, and the smoke test now checks each recording against the exact source version it cites.

## 0.2.5 — 2026-09-24

- Restores Section 6(4)(c) of the Spacecraft Crew Certification Act to its original wording: "an applicant aged 59 or under must satisfy Section 4, unless the applicant qualifies under subsection (3)." An April edit had changed it to "must always satisfy Section 4, regardless of flight hours". That contradicted Section 6(3) and differed from the copy of the Act in the published benchmark dataset. The ruleset is republished against the restored text in the next release.

## 0.2.4 — 2026-09-24

- The spacecraft example's Section 6 citation now quotes Section 6(1)–(4). Subsection (4)(b)–(c) is the text that limits the 1000-hour exemption to applicants aged 60 or over; the previous citation quoted only 6(1)–(3). The flight-hours rule is retitled to state the age condition. No decision changes. The example is repinned to v7 (`spacecraft-crew-certification:20260924-2a125fd9`).

## 0.2.3 — 2026-09-24

- Fixes the spacecraft example's Section 6 flight-hours exemption. The published ruleset applied the 1000-hour exemption at any age, so an applicant aged 30 with 1200 flight hours and no pilot licence was reported `eligible`. Section 6(4)(c) says an applicant aged 59 or under must always satisfy Section 4, so the correct outcome is `not_eligible`. The ruleset is republished as v6 (`spacecraft-crew-certification:20260924-bc511f76`) with the exemption limited to applicants aged 60 or over.
- Adds three Section 6 test cases (under-60 with 1000+ hours; 60+ on an orbital mission with and without 1000+ hours). The spacecraft demo now runs eight cases; the complete manifest has 59.

## 0.2.2 — 2026-09-16

- Replaces the engine-accuracy sentence, which did not survive a re-read of the paper it cited (v3.13.0). The 63.6% floor is GPT-5.3, a production-tier baseline whose alias the paper records as deprecated ("Replication impossible"); it is an N=11 subset with a Wilson 95% CI of [35.4%, 84.8%]; 225 is the benchmark's total size rather than any model's denominator; and §6.3 defines the Module's figures as agreement with the formal rule fixtures, which deterministic execution gives by construction.
- The replacement states the April 2026 replication range (88–100%) and cites §6.3, so a reader can check every part against the public paper.

## 0.2.1 — 2026-09-14

- Labels the dated free-school-meals teaching corpus as Aethis demonstration material.
- Corrects spacecraft orbital quote context without changing the authored decision model.
- Prepares reviewed source inputs; repaired live citation cuts remain to be verified.

## 0.2.0 — 2026-09-13

- Adds a strict agent quickstart with correlated tool evidence, input identity
  checks, bounded execution, and a free tool-only mode.
- Checks the complete recursive scenario manifest, including nested cases,
  immutable ruleset pins, expected outcomes and blocking errors.
- Adds five authored composition acceptance cases, separate from leaf scenarios.
- Adds source-reference material and the concessionary travel pass graph demo.
- Adds CI checks for proof validation, runner controls and dependency installation.
- Removes generated ruleset snapshots from the current tree.

This repository uses semantic versions for reviewed public-example releases.
