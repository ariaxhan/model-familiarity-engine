---
type: note
status: active
created: 2026-07-14
---

# Independent final release grade: MFE v0.2.0 and LHCR evidence correction

## Verdict

**APPROVE for integration**

- Critical: 0
- High: 0
- Medium: 0

The three prior release blockers are resolved. The historical Experiment 0 packet now fails
closed on provenance, protocol hashing is stable across Python 3.12 and 3.14, and the public
study planner cannot be made runnable with the historical, malformed, incomplete, or forged
packet. The source tree, public claims, package metadata, workflows, and tests are coherent for
v0.2.0 integration.

This approval does **not** approve the ignored files currently under `dist/`: they were built at
10:55, before the final hashing and planner edits at 11:35-11:44, and the old sdist contains
`_meta/`. `dist/` is gitignored and the release workflow builds new artifacts from the integrated
checkout, so these stale local files are not part of the candidate. Discard them and perform the
documented fresh build/install/archive inspection before tagging.

## Prior blocker dispositions

### Post-hoc provenance overclaim: resolved

- `lhcr/src/llm_bench/familiarity/instrument_health.py:188-248` recomputes all five shard hashes,
  but explicitly returns `FAIL`, value `retrospective only`, when the manifest lacks a genuine
  collection-time stamp.
- `lhcr/results/familiarity/runs/exp0/source-manifest.json` declares
  `binding: retrospective` and `collection_time_protocol_stamp: false`; its old protocol value is
  labeled `retrospective_protocol_label`, not collection-time proof.
- Independent recomputation matched every recorded shard digest and the manifest digest:
  `floor 5f8551...8174`, `verdicts c0b399...1a26`, `rescore b4506e...6a17`,
  `blind 5bb68e...595`, `oracle-anchor 419d08...94a2`, manifest `1d35de...c08a`.
  This proves byte custody only, exactly as the packet says.
- Live LHCR computation returned provenance `FAIL`, blinding `PASS` at exactly 40% versus 25%
  chance plus 15 percentage points, and verdict `NOT CERTIFIED` with exactly two auxiliary
  pending gates: oracle false-negative rate and human-anchor agreement.
- The MFE packaged/public copies of `gates.json`, `gate-results.md`, `health-report.md`, and
  `run-manifest.json`, plus README, changelog, methodology, and data-boundary docs, consistently
  state the same limitation and verdict.

### Python-version-dependent hashing: resolved

`_spine_fingerprint()` in both evaluators now hashes normalized source, callable identity, and
canonicalized closure values instead of `ast.dump()`. Independent executions against identical
source produced:

```text
MFE  Python 3.12.13 -> d5eef7a1a99bccee
MFE  Python 3.14.6  -> d5eef7a1a99bccee
LHCR Python 3.12.13 -> 9a730f21729df095
LHCR Python 3.14.6  -> 9a730f21729df095
```

The MFE and LHCR hashes intentionally differ because callable module identities differ across
the public port and source evaluator. README lines 134-137 disclose that distinction and do not
bind the retrospective shards to either current hash.

### Planner accepted fake provenance: resolved

`model_familiarity/study.py:293-384` now catches unreadable/invalid JSON, requires an object with
typed caveats, validates protocol/rubric/environment/panel, requires the exact reviewed manifest
digest and shard set/digests, requires collection-time binding plus a passing provenance row, and
then explicitly blocks this release's retrospective packet. Direct execution of the shipped
study config reported `measured NOT CERTIFIED -> BLOCKED`; truncated JSON reported `BLOCKED`
without a traceback. The parameterized regression suite covers missing/fake manifest, missing/fake
shard, retrospective binding, and a non-passing provenance row.

## Verification receipts

```text
MFE tests:                    179 passed in 0.51s
LHCR scoped tests:             54 passed in 0.29s
MFE ruff (src + tests):        PASS
LHCR changed-file ruff:        PASS
git diff --check, both trees:  PASS
Python compile, changed code:  PASS
JSON/YAML parse, both trees:   PASS
Source CLI version:            0.2.0
Source CLI health:             NOT CERTIFIED / provenance FAIL / two aux pending
```

All 37 MFE changed/untracked paths and all 7 LHCR changed/untracked paths were included in the
status/diff inventory. Executable changes were covered by the suites and lint; all JSON/YAML was
parsed; all Python was compiled; docs, findings, workflows, release metadata, fixtures, and
package-data boundaries were manually cross-checked. No candidate file contains the local user
home path; the only `/Users/` strings are synthetic redaction-test inputs.

## Release checklist

- [x] Historical Exp0 is **NOT CERTIFIED**.
- [x] Five shard digests prove byte custody; provenance remains **FAIL**.
- [x] Corrected blinding boundary is **PASS** at exactly chance + 15pp.
- [x] Exactly two auxiliary gates remain pending.
- [x] MFE and LHCR protocol hashes are stable on Python 3.12 and 3.14.
- [x] Study plan blocks historical, malformed, incomplete, and fake provenance.
- [x] MFE and LHCR tests and changed-code lint pass.
- [x] Version is aligned at 0.2.0 in pyproject, package `__version__`, citation, changelog,
  release documentation, tag guard, and CLI.
- [x] Workflows use SHA-pinned actions, read-only defaults, and job-scoped release permissions.
- [x] Wheel boundary is package-only and contains the packaged health/example data required by
  the CLI; sdist exclusions cover `_meta`, agent state, caches, build products, virtualenvs,
  egg-info, and bytecode.
- [ ] Before tagging, rebuild wheel/sdist from the integrated checkout, install the new wheel in
  a disposable environment, and inspect the new archives. Do not publish the stale ignored
  `dist/` files present in the surgeon worktree.

## Rubric (1-5)

- Methodological validity: **5/5**
- Public package/install journey: **4/5** (source/CLI/workflow aligned; fresh final artifact rebuild remains the tag gate)
- Privacy/supply chain: **5/5**
- Documentation/claim honesty: **5/5**
- Regression strength: **5/5**

## Report path

`_meta/reports/review-c2c92ab-working-r3/grader.md`
