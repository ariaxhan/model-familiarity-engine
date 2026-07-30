---
type: note
status: active
created: 2026-07-14
---

# Public Bedrock verdict repair

Goal: recover only the 12 contradictory judge verdicts in the immutable v1b packet,
without rerunning subject models or changing the PyPI package lane.

## Decision

Choose targeted re-adjudication into a new child packet. Reject silent normalization
because it guesses the judge's intent. Reject a full rerun because it discards valid,
already-paid subject outputs and changes the sampled observations.

## Contract

- Verify every source-packet checksum and evidence/manifest tie-out before AWS calls.
- Reuse the exact stored, redaction-checked subject output for eligible
  `strict_verdict_error/contradiction` records only.
- Retry the independent judge at most twice with an explicit consistency reminder.
- Preserve original subject timing, usage, output, task/cell identity, and sample index.
- Sum all repair-judge usage and label repaired records and the child packet visibly.
- Write a new immutable packet with parent run ID and source-manifest SHA-256.
- Publish aggregate cards only if all 150 cells complete and all ordinary gates pass.
- Maximum projected repair spend: USD 1; no infrastructure, package, or release edits.

Done when tests cover checksum rejection, ineligible errors, retry success/exhaustion,
provenance, dry-run zero calls, and non-overwrite; the live child packet verifies,
publishes, and receives adversarial review.
