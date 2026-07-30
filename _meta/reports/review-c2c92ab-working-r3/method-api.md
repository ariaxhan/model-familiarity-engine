---
type: note
status: active
created: 2026-07-14
---

# W9 method and API final re-review

Verdict: **APPROVE**

Remaining/new severity counts: critical 0, high 0, medium 0, low 0.

## R3 dispositions

| Finding | Disposition | Exact evidence |
|---|---|---|
| R2 H2: retrospective shards could be relabeled as collection-time evidence | Resolved for the v0.2 release packet | The retained LHCR manifest declares `binding: retrospective`, `collection_time_protocol_stamp: false`, and labels its old protocol value only as retrospective at `results/familiarity/runs/exp0/source-manifest.json:3-7`. Validation returns `FAIL` / `retrospective only` when those collection-time fields are absent at `src/llm_bench/familiarity/instrument_health.py:218-225`. The generated LHCR packet records the retrospective binding and `NOT CERTIFIED` verdict at `results/familiarity/runs/exp0/gates.json:25-49`, with the provenance row explicitly `FAIL` at `:109-113`. The public evaluator independently hard-codes the historical provenance gate to `FAIL` at `src/model_familiarity/instrument_health.py:142-148`; public findings, packaged data, README, and methodology use the same custody-only wording. |
| R2 M2: MFE human-anchor ties coerced to `True` | Resolved | MFE now counts true and false votes separately, drops equal splits, uses a strict majority, and reports dropped ties at `src/model_familiarity/instrument_health.py:294-319`. Regression coverage exercises both the 1-1-only case and mixed 1-1 / 2-0 / 2-1 / missing-vote rows at `tests/test_instrument_health.py:122-152`. A direct runtime assertion confirmed a 1-1 split returns `PENDING` with a tie detail, not a positive panel label. |
| R2 M3-new: malformed certification packet crashed the planner | Resolved | `_certification_state` catches I/O and JSON parse failures and validates the top-level mapping and caveat list before semantic access at `src/model_familiarity/study.py:309-322`. Regression tests cover truncated JSON, list top-level, non-list caveats, and unreadable files at `tests/test_study_config.py:403-436`. Direct execution confirmed all malformed and missing cases render `BLOCKED` without a traceback. |
| Fresh grader: fake or missing provenance could still yield `RUNNABLE` | Resolved | The planner validates the reviewed manifest digest and exact shard set/digests at `src/model_familiarity/study.py:340-358`, requires collection-time binding, a true stamp, and a passing provenance row at `:360-372`, and then applies the release trust boundary at `:373-384`. Missing packets, fabricated hashes/shards/stamps, and a forged otherwise-`CERTIFIED` packet all remain `BLOCKED`. Regression coverage is at `tests/test_study_config.py:324-400`; a direct forged-packet execution also remained `BLOCKED` with `no trusted collection-time provenance`. |
| Fresh grader: protocol hash depended on unstable interpreter bytecode/details | Resolved | Both implementations hash normalized source text plus canonicalized closure values, rather than bytecode: MFE `src/model_familiarity/instrument_health.py:58-122`; LHCR `src/llm_bench/familiarity/instrument_health.py:68-132`. Tests cover every challenge field, same-identity body changes, and same-identity closure changes at MFE `tests/test_instrument_health.py:11-84` and LHCR `tests/test_exp0.py:283-359`. Executing both implementations under Python 3.12.13 and 3.14.6 produced identical hashes per implementation: MFE `d5eef7a1a99bccee`; LHCR `9a730f21729df095`. |

## Artifact and claim synchronization

- Byte-for-byte equality passed for LHCR, public findings, and packaged-data copies of `gates.json`, `health-report.md`, and `gate-results.md`.
- Recomputed SHA-256 for `source-manifest.json` and all five retained LHCR shards matches the LHCR gate packet, public gate packet, packaged gate packet, and public run manifest.
- `findings/exp0/run-manifest.json:4-22` distinguishes the current source evaluator hash from the retrospective historical label, sets the collection-time hash to null, and reports `NOT CERTIFIED` with failed gate `provenance`.
- README `:109-138`, findings README `:3-17`, methodology `:25-36`, both Markdown gate reports, and all JSON packets agree: hashes prove byte custody only; provenance fails; the initial run is not certified; human-anchor and anchored oracle-FN gates remain pending.
- The release-local planner deliberately cannot trust a future collection-time packet without updating the reviewed release constants; this is stated in code at `src/model_familiarity/study.py:373-376` and is fail-closed for v0.2.

## Verification gates

- Direct runtime assertions passed for MFE strict tie handling; missing/truncated/non-object/non-list certification packets; and a forged all-positive provenance packet.
- Cross-interpreter protocol-hash execution passed on Python 3.12.13 and 3.14.6 for both repositories.
- Artifact equality and all six provenance SHA-256 recomputations passed.
- Built-in compilation passed for 106 Python source/test files across the two current surgeon worktrees.
- Pytest itself was not available in the reviewer's offline environments, so the focused behaviors were executed directly against the real module entry points. Parent W7 remains responsible for the complete configured pytest/ruff/build receipt.

## New findings

No new issue at medium severity or higher was found in the requested method/API scope.

## Rubric

- Evidence precision: 5/5
- Disposition completeness: 5/5
- Test validation: 4/5 (focused behavior, hashes, cross-interpreter execution, artifact equality, and compilation passed; full pytest unavailable in this reviewer environment)
- False-positive restraint: 5/5
