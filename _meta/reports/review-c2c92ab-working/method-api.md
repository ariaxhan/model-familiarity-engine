---
type: note
status: active
created: 2026-07-14
---

# W9 method and API review

Verdict: **REQUEST CHANGES**

Severity counts: critical 0, high 5, medium 5, low 0. All findings are above 80% confidence.

## High findings

### H1. Frozen studies are not bound to the certified panel and environment

Evidence: `model-familiarity-engine/src/model_familiarity/study.py:181-197` accepts a frozen
config when its hash equals global `protocol_hash()`, built from `DEFAULT_PANEL` and
`EXP0_ENV_MODEL` at `instrument_health.py:107-138`, not from the config. `study.py:133-138`
only checks role distinctness; `:230-245` repeats the global-hash comparison for RUNNABLE.

Impact: unrelated judges/environment can claim certification earned by another instrument.

Fix/test: hash the effective ordered environment/panel config or require exact certified values
(key, model, family, provider). Add frozen-plan rejection tests changing each field independently.

### H2. The provenance gate is not tied to evidence shards

Evidence: both `model-familiarity-engine/src/model_familiarity/instrument_health.py:158-161`
and `lhcr/src/llm_bench/familiarity/instrument_health.py:158-161` PASS provenance whenever the
current code yields nonempty hash/rubric strings. Shards loaded by `compute_gates()` carry no
verified protocol, while generated output is stamped with the current hash at the public port's
`:457-471`.

Impact: changing the protocol and regenerating reports can relabel stale measurements with the
new hash while provenance remains PASS.

Fix/test: stamp every source shard with hash/rubric at collection time and hard-fail missing or
mismatched shards. Test changed code/hash against unchanged old shards.

### H3. The PyPI sdist violates the declared public boundary

Evidence: `model-familiarity-engine/pyproject.toml:46-47` has no sdist exclusions. The built
`dist/model_familiarity_engine-0.2.0.tar.gz` includes `_meta/plans`, `_meta/research`, and
`_meta/reviews`, contrary to `docs/data-boundary.md:10-15` and the release research's explicit
`_meta` exclusion. It also includes real-looking personal Gmail data from
`tests/test_redact.py:61,131`.

Impact: the first immutable PyPI publish exposes internal planning/review material and needless
personal contact data.

Fix/test: add Hatch sdist exclusions for `/_meta`, replace test email with
`person@example.com`, rebuild, and assert archive allowlists for wheel and sdist.

### H4. The live cost ceiling is swallowed as an ordinary cell error

Evidence: `model-familiarity-engine/src/model_familiarity/cli.py:31-47` raises RuntimeError on
unknown/excess cost, but `pilot.py:115-129` catches every Exception, records a cell error, gathers
remaining cells, writes partial output, and returns. `cli.py:150-158` exits zero, contrary to
README `:77-79`.

Impact: a billing-safety violation is reported as success and concurrent calls can remain in
flight.

Fix/test: use a dedicated uncaught guard exception, cancel/await pending tasks, and exit nonzero.
Test a fake provider crossing the ceiling under concurrency and assert no new calls start.

### H5. The shipped LHCR environment API imports a module absent from the wheel

Evidence: `model-familiarity-engine/src/model_familiarity/conversation.py:191-207` exposes
`run_conversation_env()` and imports `model_familiarity.environment`, but neither source nor the
built wheel contains `environment.py`; no test exercises the path.

Impact: the environment-driven long-horizon replay path fails immediately with ImportError.

Fix/test: port/package the environment implementation or remove/explicitly disable the API. Add
an installed-wheel end-to-end fixture.

## Medium findings

### M1. Judge schemas accept contradictory reached/divergence pairs

Evidence: `model-familiarity-engine/src/model_familiarity/judge.py:154-186` and
`lhcr_judge.py:182-210` validate fields independently, accepting
`reached=false, divergence="equivalent"` and `reached=true, divergence="worse"`.

Impact: impossible verdicts enter observations as `parse_ok=True`.

Fix/test: enforce the cross-field invariant and test both contradiction directions in one-shot
and LHCR judges.

### M2. A two-judge split is coerced to reached=True

Evidence: both instrument-health copies use
`sum(reached_votes) >= len(reached_votes) / 2` at line 311. `[True, False]` becomes True even
though `model-familiarity-engine/src/model_familiarity/panel.py:75-81` defines a tie as None.

Impact: split panels can bias the future human-anchor certification gate.

Fix/test: require strict majority, drop/report ties, and test 1-1, 2-0, 2-1, parse-error, and
all-missing cases.

### M3. Malformed YAML shapes crash rather than validate

Evidence: `model-familiarity-engine/src/model_familiarity/study.py:93-99` checks truthiness,
then assumes mappings/lists (`design.get` at `:141-143`, exclusion `.get` at `:169-173`).

Impact: ordinary invalid configs produce AttributeError/stack traces at the public boundary.

Fix/test: validate full shapes before semantics and translate load/schema errors to ClickException;
add scalar/list/null/invalid-element fixtures.

### M4. Live results write relative to the installed module

Evidence: `model-familiarity-engine/src/model_familiarity/pilot.py:79` and `report.py:34`
derive output from `__file__.parents[2]`; CLI has no output option.

Impact: wheel installs write into environment `lib/python...`, possibly failing only after an
expensive run or storing raw output in a surprising place.

Fix/test: pass an explicit output directory, default to documented cwd/user data, create it before
provider calls, and test from outside the checkout with the installed wheel.

### M5. PyPI quick-start references a config absent from the wheel

Evidence: README `:27-31` establishes PyPI installation, then `:53-54` invokes
`configs/studies/example-behavioral-study.yaml`. The wheel contains no `configs/` tree.

Impact: two primary quick-start commands fail for PyPI users.

Fix/test: package/expose a resource-backed example or label commands checkout-only; execute every
README command in a fresh wheel-only environment.

## Files inspected

- Model Familiarity Engine: all 48 modified/untracked paths, including workflows, packaging,
  public docs/findings/config/package data, every new/changed Python module, fixtures, and tests;
  plus built wheel and sdist member lists.
- LHCR: all five changed paths (three Exp 0 artifacts, instrument health, and tests).
- Copied evaluator modules were diffed against donor LHCR implementations.

## Rubric scores

- Evidence/file-line precision: 5/5
- Methodology/API coverage: 5/5
- Test-gap quality: 5/5
- False-positive restraint: 4/5
