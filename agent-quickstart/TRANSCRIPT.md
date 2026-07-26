# Recorded terminal transcript

Every block below is real output, captured on 2026-07-26 from a macOS 15
(Darwin 25.5.0) shell against the live evaluator at `https://api.aethis.ai`
(engine `aethis-core@0.46.3`). Nothing is reconstructed or edited except for
trimming the model's long prose answer where marked.

Commands are exactly the ones in [`README.md`](README.md).

---

## 1. The free check — no model provider, no cost

```console
$ uv run agent-quickstart/quickstart.py --tool-only --allow-partial-proof
Aethis agent quickstart
  mode        tool-only (no model provider)
  evaluator   https://api.aethis.ai  (anonymous - no Aethis key)
  ruleset     aethis/spacecraft-crew-certification
  mcp server  aethis-mcp@0.15.1
  inputs      synthetic, non-sensitive

  calling aethis_decide on aethis/spacecraft-crew-certification with {'space.crew.species': 'Vogon'}

Decision
  outcome         not_eligible
  ruleset         aethis/spacecraft-crew-certification
  ruleset_id      spacecraft-crew-certification:20260517-c59647a5
  ruleset_version unknown
  content_digest  None

Replay handles
  decision_id     dec_yWlqBB9ERtHQw6FC
  inputs_hash     sha256:f27a28d009dfb8be22bea1537b7ff25ea5d8e2f46c466251b14806e348bfa750
  engine_version  aethis-core@0.46.3
  decision_time   2026-07-26T01:21:13.363792Z

Source references (0)
  (none)

PARTIAL PROOF in 2.4s - the release contract was NOT enforced.
This evaluator did not supply 3 required field(s):
  - ruleset_version is 'unknown' - a published ruleset always reports a resolved version, so this decision cannot be replayed
  - content_digest is not sha256:<64 hex> (None)
  - no criterion carries source_references - the decision is not traceable to its authority (request include_explanation, and publish the ruleset with publish-validated citations)
This run is not evidence of a fully auditable decision. Exit code 3.

$ echo $?
3
```

The Aethis half works end to end: the MCP server started, the tool was called,
the evaluator answered, and the envelope was checked. The three waived fields
are exactly the release-contract gap on the currently deployed evaluator.

Run the same command **without** `--allow-partial-proof` and the strict check
refuses it:

```console
$ uv run agent-quickstart/quickstart.py --tool-only
Aethis agent quickstart
  mode        tool-only (no model provider)
  evaluator   https://api.aethis.ai  (anonymous - no Aethis key)
  ruleset     aethis/spacecraft-crew-certification
  mcp server  aethis-mcp@0.15.1
  inputs      synthetic, non-sensitive

  calling aethis_decide on aethis/spacecraft-crew-certification with {'space.crew.species': 'Vogon'}

PROOF CHECK FAILED after 2.4s

[envelope-does-not-meet-contract] The decision envelope does not carry verifiable proof.
  - ruleset_version is 'unknown' - a published ruleset always reports a resolved version, so this decision cannot be replayed
  - content_digest is not sha256:<64 hex> (None)
  - no criterion carries source_references - the decision is not traceable to its authority (request include_explanation, and publish the ruleset with publish-validated citations)

This is the quickstart working as designed: a result that cannot be audited is not a result.
The evaluator at https://api.aethis.ai may predate the immutable-identity and source-reference contract,
or the ruleset may not yet be published with validated citations. Point --engine-url at an
evaluator that serves the current contract, or re-run with --allow-partial-proof to see
how far it gets (that mode never reports success).

$ echo $?
2
```

---

## 2. The full agent

```console
$ export ANTHROPIC_API_KEY=sk-ant-...
$ uv run agent-quickstart/quickstart.py --allow-partial-proof
Aethis agent quickstart
  mode        agent (claude-opus-4-8)
  evaluator   https://api.aethis.ai  (anonymous - no Aethis key)
  ruleset     aethis/spacecraft-crew-certification
  mcp server  aethis-mcp@0.15.1
  inputs      synthetic, non-sensitive

  tools available to the agent: aethis_schema, aethis_decide
  asking (claude-opus-4-8): I am a Vogon applying for spacecraft crew certification. Am I eligible? Use the Aethis ruleset aethis/spacecraft-crew-certification. Call aethis_schema first to learn the field names, then call aethis_decide with include_explanation set to true, and report the outcome.

Agent's answer (prose - not evidence)
  ## Outcome: ❌ Not Eligible
  
  I'm sorry to report that as a Vogon, you are **not eligible** for spacecraft crew certification under the `aethis/spacecraft-crew-certification` ruleset.
  
  ### Why
  
  The decision hinges entirely on the **species eligibility** requirement, which failed:
  
  - **Criterion: "Applicant is of an eligible species" → not satisfied**
  
  Under **Section 3 of the Spacecraft Crew Certification Act 2049**:
  - **Section 3(1)** requires the applicant to be of an eligible species.
  - **Section 3(2)** excludes Vogon nationals by virtue of the **Galactic Diplomatic Exclusion Treaty 2045**.
  - **Section 3(3)** mandates that where the applicant is a Vogon, the application **must be refused without consideration of any other requirement**.
  
  Eligible species are: Human, Magrathean, Betelgeusian, and Dolphin. Vogon is the sole ineligible species.
  
  [... prose answer trimmed ...]
Decision
  outcome         not_eligible
  ruleset         aethis/spacecraft-crew-certification
  ruleset_id      spacecraft-crew-certification:20260517-c59647a5
  ruleset_version unknown
  content_digest  None

Replay handles
  decision_id     dec_vKGzHAQfzDfADMcL
  inputs_hash     sha256:f27a28d009dfb8be22bea1537b7ff25ea5d8e2f46c466251b14806e348bfa750
  engine_version  aethis-core@0.46.3
  decision_time   2026-07-26T01:22:06.695607Z

Source references (0)
  (none)

PARTIAL PROOF in 23.3s - the release contract was NOT enforced.
This evaluator did not supply 3 required field(s):
  - ruleset_version is 'unknown' - a published ruleset always reports a resolved version, so this decision cannot be replayed
  - content_digest is not sha256:<64 hex> (None)
  - no criterion carries source_references - the decision is not traceable to its authority (request include_explanation, and publish the ruleset with publish-validated citations)
This run is not evidence of a fully auditable decision. Exit code 3.

$ echo $?
3
```

Note the shape of the output. The agent's prose is fluent, detailed, and cites
sections of the statute by number — and none of that is what the quickstart
trusts. The proof block below it is derived from the decision envelope the tool
actually returned, and it is what decides the exit code. Here it reports the
three fields the deployed evaluator cannot yet supply, so the run is labelled
PARTIAL PROOF and exits `3`.

First success — clone to a completed agent run, excluding dependency install —
was **23.3 s**.

---

## 3. Tests

```console
$ uv run agent-quickstart/smoke_test.py
ok    test_agent_run_is_proven_end_to_end
ok    test_run_without_the_tool_fails
ok    test_legacy_engine_envelope_is_rejected
ok    test_blocking_errors_beside_a_verdict_are_rejected
ok    test_missing_source_references_are_rejected
ok    test_partial_mode_waives_only_the_release_contract
ok    test_malformed_source_reference_is_rejected
ok    test_unresolved_version_is_rejected_case_insensitively
ok    test_envelope_parsing_handles_both_wire_shapes
ok    test_rendered_proof_shows_the_evidence
ok    test_fixture_citation_is_self_consistent
ok    test_content_parts_are_flattened_not_reprd
ok    test_quickstart_module_is_wired

All 13 smoke tests passed.

$ echo $?
0
```

Deterministic and offline: no Aethis credential, no model-provider key, and no
network access is used by the tests.
