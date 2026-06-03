# Canonical public-catalog management.
#
# Two manifests coexist during the converged-2-term transition:
#   - CANONICAL_RULEBOOKS.txt — the new rulebook-shaped manifest. Each entry
#     names a rulebook slug + the example directory whose
#     `scripts/publish-rulebook.sh` rebuilds it.
#   - CANONICAL_BUNDLES.txt — legacy slug-publish manifest. Kept for the
#     snapshot/seed flow which has not been ported to rulebooks yet.

.PHONY: help test \
        list-canonical-rulebooks rebuild-canonical-rulebooks \
        list-canonical-bundles snapshot-canonical-bundles \
        seed-canonical-bundles rebuild-canonical-bundles

help: ## Show this help.
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-32s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Testing ----------------------------------------------------------------

test: ## Run every example's test suite against the live API (set AETHIS_API_KEY for internal tier).
	@uv run test_all.py

# Rulebook-era (converged 2-term model) ----------------------------------

list-canonical-rulebooks: ## Print the canonical-rulebook manifest.
	@grep -vE '^\s*#|^\s*$$' CANONICAL_RULEBOOKS.txt | column -t -s '	'

rebuild-canonical-rulebooks: ## Loop publish-rulebook.sh across every canonical rulebook. Slow + LLM tokens.
	@./scripts/rebuild-rulebooks.sh

# Legacy slug-publish (retired flow; snapshot/seed not yet ported) -------

list-canonical-bundles: ## Print the legacy slug manifest (pre-converged).
	@grep -vE '^\s*#|^\s*$$' CANONICAL_BUNDLES.txt | column -t -s '	'

snapshot-canonical-bundles: ## Export current published bundles → snapshots/*.json (legacy slug flow).
	@./scripts/snapshot.sh

seed-canonical-bundles: ## Replay snapshots into ENV (legacy slug flow; dry-run; APPLY=1 to write).
	@./scripts/seed.sh

rebuild-canonical-bundles: ## Full LLM regeneration of legacy slug-published bundles. Use rebuild-canonical-rulebooks for new examples.
	@./scripts/rebuild.sh
