---
type: note
status: active
created: 2026-07-14
---

# W9 method and API re-review

Verdict: **REQUEST CHANGES**

Remaining/new severity counts: critical 0, high 1, medium 2, low 0.

## Original finding dispositions

| ID | Disposition | Evidence |
|---|---|---|
| H1 certified-role binding | Resolved | `model_familiarity/study.py:189-196` requires the exact certified environment and ordered panel; `:312-315` also binds the gates packet to the configured roles. Role-field and environment-drift tests are at `tests/test_study_config.py:135-145`. |
| H2 evidence-shard provenance | Partially resolved; high remains | LHCR now hashes five retained shards and verifies hash/rubric/roles at `llm_bench/familiarity/instrument_health.py:59-67,176-238,253-254`, and the published packet carries the resulting hashes. However, the manifest builder self-assigns the *current* protocol to old shards rather than reading collection-time protocol metadata, and the public port still ships the old hash-exists-only provenance gate. See H-R2-1. |
| H3 sdist boundary | Resolved in source; rebuild gate still required | `pyproject.toml:49-61` excludes internal/cache/build paths and test emails now use `example.com` at `tests/test_redact.py:61,131`. Existing `dist/` artifacts predate the fix and still contain `_meta`, so W7 must rebuild and inspect rather than publish those stale files. |
| H4 cost-ceiling abort | Resolved | `SafetyLimitError` is defined at `providers/base.py:9-10`, re-raised by `pilot.py:118-124`, converted to a failing Click result at `cli.py:201-212`, and live execution is restricted to concurrency 1 at `:186-188`. Regression coverage is at `tests/test_cli.py:78-123`. |
| H5 missing environment module | Resolved | The broken `run_conversation_env` API was removed; `tests/test_familiarity.py:101-104` asserts it is absent, and README `:98-101` explicitly scopes adaptive environment execution as planned rather than shipped. |
| M1 contradictory judge schema | Resolved | One-shot validation rejects contradictions at `judge.py:161-163`; LHCR does so at `lhcr_judge.py:191-193`. Both contradiction directions are tested in `tests/test_familiarity.py:82-83` and `tests/test_lhcr_judge.py:38-43`. |
| M2 human-anchor tie | Partially resolved; medium remains | LHCR now drops ties and reports counts at `llm_bench/familiarity/instrument_health.py:391-425` with tests at `tests/test_exp0.py:410-440`. The public evaluator copy still coerces a 1-1 split to True at `model_familiarity/instrument_health.py:298-324`. See M-R2-1. |
| M3 malformed YAML shapes | Resolved | `study.py:109-159` performs shape checks before semantic access; CLI wraps load/YAML failures at `cli.py:89-93`. Fixtures cover malformed mappings/lists/elements at `tests/test_study_config.py:170-192` and malformed YAML at `tests/test_cli.py:68-75`. |
| M4 installed-module output path | Resolved | CLI exposes `--output-dir` at `cli.py:151-156`; `pilot.py:80-90` and `report.py:394-408` use caller-controlled/cwd output and create it before provider execution. |
| M5 wheel-missing quick start | Resolved | README now starts with `model-familiarity study example` at `:48-55`; CLI writes a packaged resource at `cli.py:96-111`; the resource is `src/model_familiarity/data/example-study.yaml`; outside-repo behavior is tested at `tests/test_cli.py:58-65`. |

## Remaining and new findings

### H-R2-1. The source manifest still does not attest the protocol used when the shards were collected

Confidence: 95%.

Evidence:

- The five raw shards contain no `protocol_hash`, rubric, or old/new protocol identifier.
- `lhcr/src/llm_bench/familiarity/instrument_health.py:176-190`
  `build_source_manifest()` hashes arbitrary existing shard bytes and labels them with whatever
  `protocol_hash()` and `RUBRIC_VERSION` the current checkout returns.
- `validate_source_manifest():193-238` verifies that self-issued label and file immutability, but
  cannot distinguish shards collected under an earlier protocol from shards collected under the
  current protocol. Rebuilding the manifest after a protocol edit therefore recreates the
  original stale-evidence relabeling path.
- The public duplicate remains weaker still:
  `model-familiarity-engine/src/model_familiarity/instrument_health.py:158-161` marks provenance
  PASS solely because a current hash and rubric string exist.

Impact: the packet now proves which bytes were reviewed, but not that those bytes were generated
under protocol `22d80b51623db452`. “Five source shard hashes verified” overstates collection-time
provenance, and future regeneration can attach a new protocol hash to unchanged old measurements.

Required fix/test:

- Future run writers must stamp an immutable run envelope or every shard with protocol hash,
  rubric, environment, ordered panel, run ID, and collection timestamp before calls begin.
- Manifest construction must read and verify that stored envelope rather than synthesize protocol
  identity from the current checkout.
- For this legacy run, publish an explicit migration attestation containing the collection
  revision/original protocol hash, corrected-analysis revision/hash, and a review that protocol-
  bearing collection fields did not change; do not describe this as collection-time hash proof.
- Port the same fail-closed provenance behavior to MFE or remove its standalone report-generation
  surface.
- Regression: mutate current protocol while keeping a previously stamped run envelope and shards;
  rebuilding/validation must fail, not mint a new valid manifest.

### M-R2-1. The public instrument-health copy retains the human-anchor tie bug

Confidence: 100%.

Evidence: `model-familiarity-engine/src/model_familiarity/instrument_health.py:307-315` still
computes `sum(reached_votes) >= len(reached_votes) / 2`, so one True and one False becomes True.
No public-port test covers this. The corrected canonical behavior exists only in LHCR at
`llm_bench/familiarity/instrument_health.py:391-425`.

Impact: if MFE is later re-certified or given human calibration files, its gate can disagree with
the source implementation and bias panel-human agreement.

Required fix/test: port the strict-majority/tie-drop implementation and the 1-1, 2-0, 2-1,
missing-vote tests into MFE.

### M-R2-2. A malformed certification gates file still crashes the public planner

Confidence: 95%.

Evidence: `model-familiarity-engine/src/model_familiarity/study.py:291-299` checks only file
existence, then calls `json.loads(...)`, `gates.get`, and `list(caveats)` without catching
I/O/JSON errors or validating the top-level/result shapes. The CLI wrapper at `cli.py:89-93`
only surrounds the YAML config load, not `render_plan()`. Existing tests cover missing and
semantically mismatched gates, but not invalid JSON or a non-object packet.

Impact: a user-supplied malformed/truncated gates packet produces a traceback instead of a
fail-closed BLOCKED plan, despite the surrounding config boundary now handling malformed YAML.

Required fix/test: catch `OSError`/`JSONDecodeError`, require an object with typed fields, and
return BLOCKED with a concise provenance error. Test truncated JSON, list top level, non-list
caveats, and unreadable file.

## Gates and files inspected

- Re-read every file directly involved in H1-H5/M1-M5 in both fixed worktrees, plus their new
  tests, README/methodology/data-boundary text, packaged example, findings packets, and release
  packaging policy.
- Independently recomputed SHA-256 for `source-manifest.json` and all five retained LHCR shards;
  all match the values copied into the public gate/run packets.
- Parsed/compiled 109 Python source files across both worktrees with no syntax errors.
- Focused pytest execution was attempted offline. The available Python environment has none of
  pytest/click/PyYAML/httpx installed, and the isolated uv cache contains no distributions, so
  dependency resolution stopped before tests ran. No network was used. Test implementations were
  inspected line by line; parent W7 must supply the executable suite receipt.
- Existing `dist/` files were inspected and are stale pre-fix artifacts; they must not be used as
  evidence for the new sdist exclusion or published.

## Rubric

- Evidence precision: 5/5
- Disposition completeness: 5/5
- Test validation: 3/5 (source-manifest hashes and syntax verified; pytest unavailable offline)
- False-positive restraint: 5/5
