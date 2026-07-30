---
type: note
status: active
created: 2026-07-14
---

# Tear Down: public Bedrock verdict repair

reviewed: 2026-07-14
tier: 3
scope: standalone experiment runner and evidence docs only

## Risks

- **Scientific validity:** repair can become outcome-shopping. Mitigate with an exact
  eligibility rule, bounded attempts, complete attempt counts, and visible provenance.
- **Mutation:** editing v1b would erase failure evidence. Require a new immutable child.
- **Accounting:** dropping prior judge usage understates cost. Preserve old usage and add
  every repair attempt to explicit adjudication totals.
- **Prompt drift:** a general new rubric would change the experiment. Keep the original
  rubric and add only the logical invariant that the rejected response violated.
- **Selective success:** publishing only repaired successes can bias results. Attempt all
  12 eligible records exactly once under one fixed policy and retain exhausted failures.
- **Security:** source packets contain model text. Re-run fail-closed redaction and keep
  public exports aggregate-only.

## Verdict: PROCEED WITH CAVEATS

The repair is defensible only as post-run re-adjudication, never as an original clean run.
Cards and receipts must disclose the parent packet, repair policy, eligible count, repaired
count, exhausted count, and added judge calls.
