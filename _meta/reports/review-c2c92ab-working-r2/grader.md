---
type: note
status: active
created: 2026-07-14
---

# Independent release grade: Model Familiarity Engine v0.2.0 + LHCR evidence correction

## Verdict

**REQUEST CHANGES**

- Critical: 1
- High: 2
- Medium: 0

The wheel/install surface is functional and the corrected aggregate arithmetic reproduces, but the central provenance claim is not yet supportable and the supposedly canonical protocol hash is interpreter-dependent. These are release blockers for an instrument whose public contract is fail-closed certification.

## Findings

### CRITICAL — the new source manifest is a post-hoc byte manifest, not collection-time protocol provenance

Confidence: 98%.

`lhcr/src/llm_bench/familiarity/instrument_health.py:176-190` builds a new manifest by combining the *current* `protocol_hash()` with SHA-256 hashes of five already-existing result shards. `validate_source_manifest()` at lines 193-238 then proves only that the current files match that newly created manifest. None of the five retained source shards contains a collection-time `protocol_hash` or rubric field:

- `results/familiarity/runs/exp0/floor.json`: top-level keys are `env_model`, `env_reject_report_only`, `env_results`, `judges`, `n_challenges`, `passed`.
- `results/familiarity/runs/exp0/verdicts.json`: top level is an unbound list.
- `results/familiarity/runs/exp0/rescore.json`: top-level keys are `k_packets`, `repeats`, `rows`.
- `results/familiarity/runs/exp0/blind.json`: top-level keys are `chance`, `families`, `n`, `rows`.
- `results/familiarity/runs/exp0/oracle-anchor.json`: top-level keys contain no protocol/rubric identity.

Therefore the same historical shard bytes can be stamped later with a different current protocol. The claims at `mfe/findings/exp0/README.md:15-17` and the `provenance: verified` result at `mfe/findings/exp0/gate-results.md:13` overstate what this evidence proves. It proves custody of the current bytes, not that those bytes were collected under protocol `22d80b51623db452`.

Required resolution: either supply trustworthy collection-time binding (an original signed/immutable run manifest, logs, or shard-embedded protocol/rubric identity) or downgrade the public claim and provenance gate to the evidence actually available. Do not call it verified protocol provenance until that link exists.

### HIGH — `protocol_hash()` is not canonical across supported Python versions

Confidence: 99%.

The public project requires Python `>=3.10` (`mfe/pyproject.toml:12`) and claims a canonical protocol hash (`mfe/README.md:19-20`, `mfe/README.md:103-105`). The implementation fingerprints spine source with `ast.dump()` at `mfe/src/model_familiarity/instrument_health.py:90-104`; AST serialization is interpreter-version-dependent.

Independent reproduction from the identical MFE surgeon tree:

```text
Python 3.12.13 -> f37add5d3223eb68
Python 3.14.6  -> 7c8ce3453c5dd0c5
```

This means certification can pass or fail solely because the installer uses another supported Python, and a frozen config cannot be portable across the declared compatibility range. The existing tests prove repeatability only inside one interpreter.

Required resolution: define a version-independent semantic serialization (or explicitly version and pin the hash algorithm/runtime), add a cross-version fixture with one expected hash, and update/re-certify all packets affected by the corrected algorithm.

### HIGH — the public study planner accepts missing or tampered shard provenance as RUNNABLE

Confidence: 99%.

`mfe/src/model_familiarity/study.py:281-322` validates only verdict rank, protocol hash, rubric, environment, and panel. It never requires or validates `source_manifest_sha256` or `source_shards`, even though the release criterion requires shard provenance to fail closed.

Independent reproduction created otherwise-valid in-memory gate packets matching the live public hash/panel/environment:

```text
missing source_manifest_sha256 and source_shards -> RUNNABLE
source_manifest_sha256 = 000... and one fake shard hash -> RUNNABLE
```

Required resolution: validate the packet's provenance schema and trusted digest/material before returning RUNNABLE, and add negative tests for missing, malformed, incomplete, and tampered provenance fields. If private shards cannot be revalidated publicly, the planner must use an explicitly trusted signed/release-bound aggregate manifest rather than silently accepting arbitrary hash claims.

## Release checklist

- [x] Public claims say **CONDITIONALLY CERTIFIED**, with the two pending gates named.
- [x] Corrected 40% vs 25% + 15pp boundary reproduces as PASS using exact rational comparison.
- [x] LHCR recomputation returns protocol `22d80b51623db452`, five current shard hashes verified, and `CONDITIONALLY CERTIFIED`.
- [ ] Collection-time protocol-to-shard provenance is established. **Blocked: critical finding.**
- [ ] Protocol hash is stable across all supported Python versions. **Blocked: high finding.**
- [ ] Public planner fails closed on missing/tampered shard provenance. **Blocked: high finding.**
- [x] MFE wheel contains package data required by `health`, `study example`, and sample tasks.
- [x] Wheel modules match the current surgeon source bytes; all 23 import successfully outside the checkout.
- [x] Installed-wheel quick start works outside the checkout: version, health, JSON health, study example, validate, plan, and zero-call run preview.
- [x] Live-cost failure is nonzero (`tests/test_cli.py:92-113`) and `SafetyLimitError` escapes the pilot's ordinary per-cell error handling.
- [x] Wheel/sdist inspection found no private `_meta` payload, private home path, secret value, raw transcript data, or ranking-result data. Mentions of excluded data and generic redaction fixtures are documentation/tests, not leaked records.
- [x] GitHub Actions are commit-SHA pinned; default workflow permissions are read-only and elevated permissions are job-scoped (`id-token: write` for PyPI, `contents: write` for GitHub release).
- [x] Version metadata aligns at `0.2.0` in `pyproject.toml`, package `__version__`, `CITATION.cff`, and `CHANGELOG.md`; the tag workflow rejects a tag not equal to `v{project.version}`.

## Gate outputs

```text
MFE: 165 passed in 0.35s
MFE ruff: All checks passed
LHCR scoped: 53 passed in 0.30s
LHCR changed-file ruff: All checks passed
LHCR protocol: 22d80b51623db452
LHCR provenance function: PASS, five current shard hashes match source-manifest.json
LHCR verdict: CONDITIONALLY CERTIFIED
Installed wheel: model-familiarity 0.2.0; 23 package modules imported
Wheel SHA-256: a1200fc3b469148c1ccc4385c2325b8072ba7623bc6ed20603e9b03fa006a881
sdist SHA-256: 9e9286d3fdf987f4175fa56abeeba589db56b0f747de4a8accba8adf77698b26
Fresh independent build: not run because hatchling was unavailable in the offline cache; the existing surgeon artifacts were byte/source inspected instead.
```

One false-negative test run was discarded: the shared LHCR editable venv initially loaded stale `/private/tmp` bytecode. Re-running with the candidate `PYTHONPATH` and a fresh `PYTHONPYCACHEPREFIX` produced the reported 53/53 result.

## Rubric (1-5)

- Methodological validity: **1/5** — corrected arithmetic is sound, but protocol provenance is not established and hashing is runtime-dependent.
- Public package/install journey: **4/5** — wheel quick start and imports work; planner provenance enforcement is incomplete.
- Privacy/supply chain: **5/5** — inspected artifacts are clean; workflows are pinned and least-privilege by job.
- Documentation/claim honesty: **2/5** — conditional caveats are honest, but “verified” protocol provenance is stronger than the evidence.
- Regression strength: **4/5** — 165 MFE and 53 LHCR tests pass with strong negative cases, but cross-version hashing and public shard-provenance rejection are untested.

## Report path

`_meta/reports/review-c2c92ab-working-r2/grader.md`
