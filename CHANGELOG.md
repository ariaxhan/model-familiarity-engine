# Changelog

All notable changes follow Keep a Changelog. Releases use semantic version tags.

## [0.2.0] - 2026-07-14

### Added

- Public long-horizon conversational replay evaluator with eight genericized challenges.
- Preregistered study validator and zero-call execution planner.
- Package-safe aggregate Experiment 0 findings and run manifest.
- Offline health CLI and guarded live replay CLI.
- CI, tag-triggered PyPI/GitHub release workflow, security policy, and citation metadata.

### Changed

- Repositioned the project as an instrument-gated evaluation engine.
- Made cloud dependencies optional and configured the wheel explicitly.
- Expanded the protocol hash to cover the full challenge schema and deterministic-spine
  semantics.
- Made protocol hashing interpreter-independent by normalizing spine source text instead of
  serializing a version-specific Python AST.

### Fixed

- Compare blinding accuracy with exact rational arithmetic; the observed 40% correctly passes
  the 25% chance + 15 percentage-point boundary.
- Reject string booleans, malformed dimensions, invalid trap flags, and invalid divergence
  labels in judge output.
- Block study plans when a certification packet's protocol hash or rubric does not match.
- Fail provenance closed when historical shards lack a collection-time protocol/rubric stamp.

### Result

- Initial Experiment 0 verdict: NOT CERTIFIED because provenance is retrospective, not
  collection-time.
- The corrected blinding-boundary gate passes; human-anchor agreement and oracle
  false-negative rate remain pending.

[0.2.0]: https://github.com/ariaxhan/model-familiarity-engine/releases/tag/v0.2.0
