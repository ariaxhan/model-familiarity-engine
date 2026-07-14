# Experiment 0: aggregate instrument-health findings

Experiment 0 evaluates the measuring instrument, not which model is best. The initial source
run is NOT CERTIFIED. The retained shards contain no collection-time protocol or rubric stamp,
so a retrospective manifest can prove byte custody but cannot prove which protocol collected
them. The current source evaluator hash is `9a730f21729df095`; this is not retroactively assigned
to the historical shards.

The provider-blinding maximum was exactly 40% against 25% chance with a registered 15
percentage-point allowance. Exact comparison places 40% on the allowed boundary, so the gate
passes. The prior failure was a binary floating-point boundary error.

The corrected blinding-boundary gate and the other measured non-provenance core gates pass.
Provenance fails, while human-anchor agreement and anchored oracle false-negative rate remain
pending. The packet contains no raw transcript, answer key, per-model score, ranking, winner,
or routing recommendation.

The aggregate packet records the frozen roles and SHA-256 hashes of five retained result
shards. Those hashes permit custody checks only. They do not bind the historical collection to
the current protocol or rubric, and the raw shards are not public.

Artifacts:

- `gates.json`: machine-readable aggregate gates and caveats;
- `gate-results.md`: reviewed gate table;
- `health-report.md`: human-readable instrument-health report;
- `run-manifest.json`: non-identifying counts and provenance.
