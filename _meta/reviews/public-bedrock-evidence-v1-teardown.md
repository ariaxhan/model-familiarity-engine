# Tear Down: public Bedrock evidence v1

reviewed: 2026-07-14
tier: 3
scope: 7 new path groups; no package or release files

## Big 5

input_validation: proceed - parse and reject model IDs, k, concurrency, budget, and paths
edge_cases: proceed - tests required for k boundary, empty evidence, errors, and partial cells
error_handling: proceed - every attempted call must end as success or explicit error evidence
duplication: proceed - one aggregator renders both summary and cards from the same records
complexity: proceed with caveat - keep AWS execution, aggregation, and rendering separable

## Security

Use the named AWS profile only through boto3/environment resolution. Store no account ARN,
credentials, raw SDK response, home path, private task, or reasoning trace. Run the existing
redaction verifier over every public text artifact before finalizing.

## Testing

Tests must precede implementation and cover invalid k, exact k=5, malformed strict judge
output, incomplete cells, Wilson interval boundaries, deterministic checksums, and dry-run
performing zero provider calls. Exercise one real AWS floor and one subject smoke before the
bounded full run.

## Verdict: PROCEED WITH CAVEATS

The experiment is safe only as a narrow synthetic-debugging snapshot. The cards must name
the model IDs, date, corpus size, judge, repetitions, uncertainty, and limitations; no broad
"best model" or production-routing claim is supported.

## Action items

1. Enforce the USD 5 projected-cost ceiling before AWS calls.
2. Treat invalid judge JSON types/divergence as failed samples, not coerced verdicts.
3. Make partial/error-heavy runs visibly non-publishable.
4. Keep the full change disjoint from the active PyPI worktree.
