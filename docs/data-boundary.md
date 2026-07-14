# Public data boundary

Published:

- genericized challenge specifications and synthetic sample tasks;
- evaluator and study-planning code;
- aggregate gate values and named caveats;
- non-identifying run counts and retrospective byte-custody metadata, including hashes of
  retained private source shards (the shard contents are not published). These hashes are not
  collection-time protocol provenance.

Excluded:

- raw or lightly redacted transcripts and reasoning traces;
- calibration packets, answer keys, and human scoring sheets;
- old scorecards, leaderboards, model rankings, or routing recommendations;
- credentials, cloud profiles, account identifiers, local paths, internal notes, and handoffs.

Runtime-generated outputs belong in ignored `results/` storage. A separate review and consent
decision is required before releasing any transcript-level dataset.
