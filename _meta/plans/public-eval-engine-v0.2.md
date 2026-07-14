# Public eval engine v0.2

Goal: make `model-familiarity-engine` a self-contained public evaluation engine with a
release-safe initial instrument-validation result.

## Approaches considered

1. Literal Git merge: rejected; imports, identity, private artifacts, and history are wrong.
2. Depend on private LHCR: rejected; the public repository would not be self-contained.
3. Selective port: chosen; preserve MFE history and package identity while porting only the
   evaluator, offline study planner, tests, and reviewed aggregate result artifacts.

## Sequence

1. Fix LHCR certification boundary and protocol-hash coverage; regenerate Exp 0.
2. Port the corrected evaluator plus `05b9cfc` study planner into `model_familiarity`.
3. Add strict schemas, safe/configurable CLI, package-data layout, CI, README, security and
   citation metadata, aggregate findings, changelog, and version 0.2.0.
4. Configure GitHub description/topics. Prepare tag and release notes after all gates pass.

Done when a fresh environment installs the wheel, offline `health` and `study plan` work,
all tests/lint/security gates pass, public-data scans are clean, and the README states both
the initial result and what it does not support.

