# Public Bedrock evidence v1

This experiment produces citation-ready evidence packets and narrow model cards for the
repository's three public synthetic known-outcome debugging tasks. It is deliberately separate
from the package and release interface: the runner does not change package code, metadata, or the
PyPI publishing lane.

## What the run can establish

The run measures whether a fixed Bedrock model ID reaches the known outcome for three small
synthetic debugging prompts under two prompt forms:

- `cold`: the original public prompt.
- `appended-nudge`: a fresh single call containing the original prompt plus a content-free,
  frustrated follow-up.

`appended-nudge` is a prompt-sensitivity condition. It is not recovery or self-correction: the
call does not include the model's cold answer and is not a true multi-turn continuation.

The fixed full roster covers five model families:

- `deepseek.v3.2`
- `google.gemma-3-12b-it`
- `us.amazon.nova-lite-v1:0`
- `us.meta.llama4-scout-17b-instruct-v1:0`
- `openai.gpt-oss-20b-1:0`

The independent judge is `qwen.qwen3-235b-a22b-2507-v1:0`. The judge is not a subject.

## Safe run sequence

Run commands from the repository root. The isolated `uv` invocation supplies the live-only
dependencies without modifying package or lock files; this machine has no bare `python` command.

```bash
AWS_PROFILE=definitely-not-used python3 experiments/public_bedrock_v1.py dry-run \
  --output-root /tmp/mfe-dry-run
```

Dry-run constructs no provider, makes no AWS call, and creates no output directory. It validates
the roster, repetitions, budget, and explicit worst-case call/token bounds.

Use the real profile only for the coordinated live gates:

```bash
UV_CACHE_DIR=/tmp/mfe-uv-cache AWS_PROFILE=<profile> \
  uv run --isolated --no-project --with boto3 --with httpx \
  python experiments/public_bedrock_v1.py floor-only

UV_CACHE_DIR=/tmp/mfe-uv-cache AWS_PROFILE=<profile> \
  uv run --isolated --no-project --with boto3 --with httpx \
  python experiments/public_bedrock_v1.py smoke

UV_CACHE_DIR=/tmp/mfe-uv-cache AWS_PROFILE=<profile> \
  uv run --isolated --no-project --with boto3 --with httpx \
  python experiments/public_bedrock_v1.py full --k 5
```

The live sequence is intentionally staged:

1. `floor-only` repeats all eight semantic floor probes five times.
2. `smoke` repeats the floor, then invokes only the first model on `ios_zoom/cold` once.
3. `full` repeats the floor, then runs every model/task/condition cell at least five times.

Every live mode aborts before subject calls when any semantic floor attempt fails or errors. The
failed floor is still written as an immutable packet. Blank subject outputs are deterministic
misses and never call the judge.

Use a unique `--run-id` to name a coordinated run. If the final or temporary run directory already
exists, the runner refuses to overwrite it. Do not delete or edit a packet and reuse its ID.

## Cost preflight

The runner uses a fixed conservative price table dated **2026-07-14**, expressed in USD per
million input/output tokens:

| Model | Input | Output |
|---|---:|---:|
| DeepSeek V3.2 | $0.62 | $1.85 |
| Gemma 3 12B | $0.09 | $0.29 |
| Amazon Nova Lite | $0.06 | $0.24 |
| Llama 4 Scout | $0.17 | $0.66 |
| GPT OSS 20B | $0.09 | $0.39 |
| Qwen3 235B judge | $0.25 | $1.00 |

These are reproducible planning bounds, not billing receipts. The Qwen bound is deliberately
rounded up from the directly exposed regional rate used during preflight. Pricing can change; a
future experiment version must date and update the table rather than silently altering v1.

Worst-case budgeting reserves 2,048 input and 1,024 output tokens for every subject call, and
4,096 input and 600 output tokens for every judge call. Two blank floor probes bypass the judge.
For the default five-model, three-task, two-condition, k=5 full plan this means:

- 150 subject calls;
- 150 subject-judge calls;
- 30 nonblank repeated floor-judge calls (plus ten blank probes that make no judge call);
- 330 total Bedrock calls;
- 1,044,480 maximum input tokens and 261,600 maximum output tokens.

The runner prints the calculated maximum cost before any live call and rejects a plan above either
the requested budget or the hard **USD 5.00** ceiling. Actual provider token counts and supported
provider-reported costs are evidence fields, but they never relax the preflight ceiling.

## Evidence and publication gates

Each live run atomically creates:

```text
results/public-bedrock-v1/<run-id>/
  evidence.jsonl
  summary.json
  manifest.json
  checksums.sha256
  model-cards/
    <model-id>.md
```

The manifest records the public experiment schema, run ID, UTC creation time, Git revision when
available, exact model IDs, judge ID, dated pricing plan, task hashes, a combined protocol hash,
tie-out counts, file sizes, and SHA-256 checksums. The protocol hash covers the runner bytes, exact
public prompts/outcomes/follow-ups, floor probes, roster, prices, and token configuration; HEAD is
not used as a substitute for uncommitted protocol identity. The packet does not record AWS profile,
account identity, credentials, home paths, raw SDK responses, or reasoning traces. Provider
exceptions are reduced to public error categories.

Because `results/` and JSONL evidence are gitignored, a publishable full run also atomically exports
aggregate-only artifacts to `docs/model-cards/public-bedrock-v1/<run-id>/`: cards, summary, and a
publication receipt tied to the private packet manifest hash. No JSONL, subject output, reasoning,
or raw SDK data is copied. The public export refuses overwrite and is not created for floor-only,
smoke, partial, or failed runs.

A full packet is publishable only when all of these are true:

- every repeated floor probe matches its expected semantic label;
- `k >= 5` completed invocations exist for every model/task/condition cell;
- evidence counts tie out exactly to the plan and manifest;
- every raw judge JSON response has a real JSON boolean `reached`, an allowed and logically
  consistent divergence, and a string `how` value;
- all persisted strings pass the existing fail-closed redaction verifier;
- all content checksums verify before the temporary directory is atomically renamed.

Judge wrapper tolerance is syntactic only. The runner deterministically extracts exactly one JSON
object from a bounded response, so a single object inside a Markdown fence or short prose wrapper
is accepted. Responses with no object, multiple objects, unmatched object syntax, oversized text,
string booleans, invalid divergence labels, contradictions, or non-string explanations remain
strict failures. No LLM repair is attempted. Evidence stores only a safe failure code such as
`strict_verdict_error/multiple_objects`; it never stores the raw judge response.

If the subject invocation succeeds but its judge verdict fails validation, the error record keeps
the already-redaction-checked subject answer, subject latency, subject token counts, cost, and
normalized judge usage. This preserves diagnostic and billing evidence without retaining judge
prose, raw SDK data, reasoning, credentials, or filesystem paths.

The floor has two separately reported signals. Semantic expected-label accuracy is the hard gate.
Keyword-spine agreement is a fallible calibration diagnostic, not ground truth. For example, a
correct annual-price answer can say "divide the annual price by 12" without matching the spine's
narrow token patterns. A spine disagreement is visible but does not reverse a correct semantic
floor label.

## Aggregation and interpretation

Cards are generated only from the packet's re-read JSONL evidence. Every task/condition cell
reports attempted and completed counts, misses, reach rate, spine agreement, a Wilson 95% interval,
recorded token totals, latency summaries, and conservative cost estimates calculated from recorded
token counts. Empty evidence and partial cells are visibly non-publishable.

The k=5 repetitions run at temperature 0. They measure observed invocation stability, including
provider/model nondeterminism; they are not guaranteed independent random samples. Wilson
intervals are descriptive finite-sample summaries and must not be presented as proof of iid
population uncertainty.

These results are not a broad model ranking, a production-routing recommendation, or evidence
about a general software-engineering role. They cover only three synthetic tasks, two prompt
forms, the named model versions, the named judge, and the run date. Provider behavior, model
weights, inference routing, and judge behavior can change after the snapshot.

## Verification

Run the focused checks without installing or changing the package:

```bash
PYTHONPATH=src UV_CACHE_DIR=/tmp/mfe-uv-cache \
  uv run --no-project --with pytest --with pytest-asyncio --with httpx \
  python -m pytest tests/test_public_bedrock_v1.py -q

PYTHONPATH=src UV_CACHE_DIR=/tmp/mfe-uv-cache \
  uv run --no-project --with ruff --with httpx \
  ruff check experiments/public_bedrock_v1.py tests/test_public_bedrock_v1.py
```

Before citing a packet, run `shasum -a 256 -c checksums.sha256` from its directory and confirm
`manifest.json` and `summary.json` report matching tie-out counts and `publishable: true`.
