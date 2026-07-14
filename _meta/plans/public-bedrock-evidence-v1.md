# Public Bedrock evidence v1

Goal: produce a reproducible, citation-ready Bedrock experiment packet and narrow model
cards without changing the package or its PyPI release lane.

## Contract

- Inputs: the three public synthetic known-outcome tasks, versioned Bedrock model IDs,
  and the independent Qwen judge already exposed by the package.
- Outputs: a standalone runner, tests, immutable evidence, checksums, aggregate cards,
  and a methodology/limitations note.
- Budget: on-demand inference only, no provisioned infrastructure, maximum projected
  spend USD 5, k >= 5 completed samples per model/task/condition cell.
- Forbidden: `src/**`, `pyproject.toml`, `README.md`, version/tag/upload/push changes.

## Approaches considered

1. Re-run the fixed pilot five times (~20 lines shell, no dependencies): rejected because
   it overwrites outputs and loses sample identity and failed-run provenance.
2. Add repeat/configuration support to the package CLI (~180 lines, existing deps):
   rejected because it overlaps the active PyPI lane.
3. Standalone experiment runner (~350 lines, standard library + package APIs): chosen;
   it keeps release interfaces stable and can atomically write an immutable run packet.

## Required gates

1. Dry-run validates models, k, call/token ceilings, projected worst-case cost, and paths
   before any AWS call.
2. Repeat every live floor probe at least five times; abort before subject calls on failure.
3. Record every attempted cell, strict judge-schema failure, AWS error, token count, model
   ID, task hash, code revision when available, timestamp, and sample index.
4. Publish Wilson 95% intervals and completion/error counts; never promote synthetic
   debugging results into general model rankings or role claims.
5. Regenerate cards only from the immutable JSONL evidence and verify SHA-256 checksums.

Done when the live floor passes, all publishable cells have k >= 5 completed samples,
artifacts tie out to the manifest, unit tests/lint/full tests pass, and an adversarial
review finds no unsupported claims or leaked private data.
