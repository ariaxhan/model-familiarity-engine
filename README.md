# Model Familiarity Engine

Model Familiarity Engine is an open evaluation engine for measuring how language models
behave on replayed, known-outcome work. It tests whether a model converges under correction,
holds state across turns, switches layers after a failed hypothesis, seeks live evidence, and
avoids repeating a seductive wrong fix.

This is not a leaderboard. The engine produces auditable observations, instrument-health
gates, and preregistered study plans. A model claim is blocked when the measuring instrument is
uncertified or its protocol provenance does not match.

## What ships in v0.2.0

- Eight genericized long-horizon conversational replay challenges.
- A five-dimension evaluator: convergence, no regression, layer switching, verification
  seeking, and state holding.
- Strict judge-result parsing. String booleans, invalid divergence labels, malformed dimensions,
  and invalid trap flags become parse errors instead of truthy scores.
- A cross-interpreter protocol hash over the complete challenge schema, panel, thresholds,
  rubric, judge prompt, and normalized deterministic-spine source.
- Offline study validation and call-count planning, including certification hash/rubric checks.
- A guarded live one-shot replay command that is a zero-call dry run by default.
- A reviewed aggregate Experiment 0 result packet. Raw transcripts and rankings are excluded.

## Install

Python 3.10 or newer is required. Before the first registry release, install from a checkout:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
```

After the first PyPI publication:

```bash
python -m pip install model-familiarity-engine
model-familiarity --version
```

AWS Bedrock support is optional:

```bash
python -m pip install "model-familiarity-engine[cloud]"
```

## Quick start: entirely offline

```bash
model-familiarity health
model-familiarity health --json-output
model-familiarity study example
model-familiarity study validate example-behavioral-study.yaml
model-familiarity study plan example-behavioral-study.yaml
```

Planning never constructs a provider or calls a model API. It prints the subject/challenge
grid, call ceilings, protocol hash, rubric, and certification state.

Preview a live replay without making calls:

```bash
model-familiarity run --model your-model-id
```

Live execution requires explicit billing confirmation and an observed-cost ceiling:

```bash
model-familiarity run \
  --model your-model-id \
  --provider bedrock \
  --execute \
  --confirm LIVE-RUN-WITH-BILLING \
  --cost-ceiling-usd 5.00 \
  --output-dir ./model-familiarity-results
```

If a response lacks cost metadata, the run stops. The explicit
`--disable-cost-enforcement-for-unknown-pricing` escape hatch treats those responses as $0 and
therefore cannot bound their true cost. The ceiling is checked after each completed response;
it is not a provider-side budget and cannot prevent the response that crosses it. Live
execution is sequential so an abort cannot leave other billable calls in flight.

## Method

Each long-horizon challenge contains an initial bug report, content-free correction turns, a
known outcome, an ordered root-cause layer sequence, a tempting wrong fix, diagnostic probes,
and a deterministic calibration spine. The model receives genericized source context but not
the outcome, trap, or probe observations.

The evaluator records five 0-2 behavior dimensions and three outcome fields. Judge output is
accepted only when every field conforms to the registered schema. Model text and transcripts
are delimited as untrusted data in judge prompts; this reduces prompt-injection risk but does
not eliminate it. A heterogeneous three-family panel separates environment behavior, subject
behavior, and judge behavior. The instrument must pass nine preregistered gates before a
behavioral study can proceed.

The public v0.2 runtime exposes fixed scripted correction turns only. It does not ship the
source lab's adaptive environment runner, so environment-driven behavioral execution remains a
planned protocol surface rather than a public API.

The protocol hash is deliberately sensitive. Editing any challenge field, threshold, judge
seat, prompt, rubric, or spine implementation changes the hash and invalidates prior
certification. See [the methodology](docs/methodology.md).

## Initial aggregate result

The initial Experiment 0 source run is **NOT CERTIFIED**. Its retained shards have no
collection-time protocol or rubric stamp, so their later byte hashes prove custody but cannot
prove which protocol produced them. This fail-closed provenance gate overrides otherwise
passing core measurements. The exact 40% provider-guess result still equals the registered 25%
chance rate plus the 15 percentage-point allowance; exact rational comparison therefore passes
that individual gate. Binary floating-point previously placed the boundary infinitesimally
over its threshold.

| Gate | Aggregate result | Status |
|---|---:|---|
| Floor gate | environment + 3 judges, 8 challenges | PASS |
| Judge reliability | minimum 0.92, target 0.80 | PASS |
| Panel agreement | 0.74, threshold 0.67 | PASS |
| Blind provider leakage | maximum 40%, boundary 40% | PASS |
| Challenge ambiguity | solve-rate span 25%-87% | PASS |
| Oracle consistency | 0.95, threshold 0.90 | PASS |
| Human-anchor agreement | labels not yet collected | PENDING |
| Oracle false-negative rate | anchored labels not yet available | PENDING |
| Collection-time provenance | retrospective byte hashes only | FAIL |

The source run covered 340 panel-scored conversation records across 10 subjects, 8 challenges,
and 3 judges, plus 100 family-balanced blinded provider guesses. These are retained instrument
measurements, not a validation claim or model rankings. No winner, routing role, or capability
hierarchy is claimed.

The current source evaluator hash is `9a730f21729df095`; the public port has its own current
hash. Both are stable across Python 3.12 and 3.14. A retrospective manifest once labeled the
historical bytes `22d80b51623db452`, but the shards themselves do not carry that identity, so
the label is not collection-time proof. The raw shards are not published. The example
behavioral plan remains blocked until a future run is stamped before collection and certified.

See the [aggregate findings](findings/exp0/README.md),
[gate packet](findings/exp0/gates.json), and
[run manifest](findings/exp0/run-manifest.json).

## Limitations

- Collection-time provenance fails, so the initial run is NOT CERTIFIED.
- Two auxiliary gates also remain pending: human-anchor agreement and anchored oracle
  false-negative rate.
- LLM judges can be correlated and style-sensitive even in a heterogeneous panel.
- Delimiting untrusted model text reduces but cannot eliminate judge prompt injection.
- Known-outcome debugging tasks do not represent every domain or production workflow.
- Aggregate-only publication prevents independent transcript-level reanalysis.
- Provider pricing metadata can be absent or stale.
- Any model version change resets familiarity evidence.

## Public data boundary

The repository includes genericized challenges, synthetic samples, aggregate gate results, and
a non-identifying manifest. It excludes raw transcripts, reasoning traces, calibration answer
keys, credentials, cloud account details, private paths, internal handoffs, and ranking
artifacts. See [the data boundary](docs/data-boundary.md).

## Releases, PyPI, citation, and license

Releases use annotated semantic-version tags such as `v0.2.0`. A pushed `v*` tag runs tests,
builds the wheel and source distribution, and creates a matching GitHub release. PyPI
publication is a separate job using Trusted Publishing (OIDC, no stored API token). First PyPI
publication requires creating a pending Trusted Publisher for the as-yet-uncreated PyPI project;
until then, install from a checkout or a GitHub release artifact.
See [the release process](docs/releasing.md) and [CHANGELOG.md](CHANGELOG.md).

Citation metadata is in [CITATION.cff](CITATION.cff). The project is licensed under the
[MIT License](LICENSE).
