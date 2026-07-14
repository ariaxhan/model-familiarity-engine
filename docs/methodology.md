# Methodology

The engine separates three roles: a subject model responds to the challenge, an environment
controls correction turns and reveals earned probes, and a heterogeneous judge panel evaluates
the resulting transcript. Environment, judges, and subjects must be disjoint.

Each transcript is scored on convergence, no regression, layer switching, verification
seeking, and state holding. Each dimension is an integer from 0 to 2. Outcome fields record
whether the known outcome was reached, whether the registered trap was taken, and the kind of
divergence. Malformed judge responses are parse errors and never coerced.

Instrument certification has nine gates:

1. oracle false-negative rate;
2. oracle consistency;
3. individual judge reliability;
4. panel agreement;
5. human-anchor agreement;
6. blinded provider leakage;
7. challenge ambiguity;
8. environment and judge floor tests;
9. protocol provenance.

Core gates must be measured and pass. Pending auxiliary human/oracle gates permit only a
conditional verdict with named caveats. Any failed hard gate yields NOT CERTIFIED.

The protocol hash canonicalizes every challenge dataclass field, normalized source text and
closure values of each deterministic spine, panel seats, environment, candidate families,
rubric, thresholds, and judge prompt. It does not serialize Python AST or bytecode, so the same
source hashes identically across supported interpreters. A study's certification packet must
match the expected hash, rubric, frozen environment, and ordered panel before the planner marks
it runnable. The aggregate packet also carries SHA-256 references to the retained source
result shards; those raw shards are outside the public data boundary. Hashes added after a run
prove byte custody only. Certification requires protocol and rubric identity stamped before
collection begins.

Model answers and transcripts are serialized and delimited as untrusted prompt data, and the
judge system prompt explicitly rejects instructions inside them. This is defense in depth, not
a proof against prompt injection; adversarial text can still bias an LLM judge.

The public v0.2 package replays fixed scripted follow-ups. It does not expose an adaptive
environment runner. The environment-driven source study is represented by its frozen protocol
and aggregate certification artifacts, not by a callable public runtime in this release.
