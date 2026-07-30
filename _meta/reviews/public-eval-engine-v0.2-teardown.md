---
type: note
status: active
created: 2026-07-14
---

# Tear Down: public eval engine v0.2

reviewed: 2026-07-14
tier: 3
scope: multi-repository selective port

## Big 5

input_validation: revise - strict judge and study schemas required
edge_cases: revise - threshold equality and missing result shards require tests
error_handling: pass with caveat - CLI must fail before network/cost on invalid plans
duplication: pass - one canonical evaluator namespace after port
complexity: pass with caveat - exclude unrelated benchmark and gallery code

## Verdict: PROCEED WITH CAVEATS

The selective-port architecture is sound only if certification defects are fixed first and
public artifacts remain aggregate, immutable, and caveated. A literal merge is rejected.

## Action items

1. Add red tests for exact threshold equality and every protocol-bearing hash field.
2. Add red tests for string booleans, invalid divergence, fresh install, and dry-run safety.
3. Withhold raw transcripts, calibration answer keys, private paths, and model rankings.
4. Require a separate post-change methodology and public-release grader before tagging.
