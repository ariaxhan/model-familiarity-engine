---
topic: lhcr-public-merge
date: 2026-07-14
source_heads: model-familiarity-engine@515f3c6, lhcr@d53f5e7, study@05b9cfc
---

# Failure-mode map

## Release blockers

1. Exp 0's blinding boundary is misclassified by float subtraction: 40/100 is exactly
   the allowed 25% + 15pp boundary, but becomes `0.15000000000000002`.
2. `protocol_hash()` omits protocol-bearing prompt, probe, context, and fix fields.
3. The public package cannot be installed because Hatch cannot infer `src/model_familiarity`.
4. Judge JSON coercion accepts string booleans and marks invalid divergence as parsed.
5. The public CLI launches a fixed 32-model Bedrock sweep with no dry-run or cost preview.
6. A wholesale LHCR merge would publish private paths, cloud defaults, internal metadata,
   legacy `llm_bench` identity, and uncertified rankings.
7. Results are ignored and lack an immutable public run manifest.

## Required controls

- Fix and regression-test certification arithmetic and full protocol hashing before porting.
- Selectively port evaluator and study-planning code; migrate imports mechanically.
- Publish aggregate instrument-validation artifacts only. Exclude transcripts, answer keys,
  legacy cards/leaderboards, `_meta`, Obsidian state, credentials, and infrastructure IDs.
- Label model-level conclusions unsupported. Publish evaluator findings and pending gates.
- Verify clean-wheel install, offline commands, CI, tests, lint, dependency audit, and secret scan.

