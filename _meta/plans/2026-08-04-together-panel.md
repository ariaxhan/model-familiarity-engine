---
type: plan
status: built, blocked on credential
created: 2026-08-04
scope: Add a Together serverless panel (Kimi K3, GLM-5.2, DeepSeek V4, MiniMax M3, Qwen3.5-3.7) as a separate study
---

# Together panel

A **second panel**, not a migration. The Bedrock 32-model panel in `pilot.py` is untouched
and its protocol hash is unchanged.

## Why separate rather than swapped

Together stocks newer generations than Bedrock pins:

| Bedrock panel pins | Together serves |
|---|---|
| `deepseek.v3.2`, `us.deepseek.r1-v1:0` | DeepSeek **V4** Pro / V4 Flash |
| `zai.glm-4.7`, `zai.glm-5` | GLM-**5.2** |
| `moonshotai.kimi-k2.5` | Kimi **K3**, K2.7-Code, K2.6 |
| `minimax.minimax-m2.5` | MiniMax **M3** |
| `qwen.qwen3-32b-v1:0` | Qwen**3.5 / 3.6 / 3.7** |

Different version means different subject. Treating GLM-4.7 and GLM-5.2 as one row would be
exactly the reputation-over-evidence move `VISION.md` exists to refuse. So this lands as a
new panel with its own protocol hash, and cards from it are never compared against Bedrock
cards.

Also absent from Together entirely: Mistral, Gemma, Nemotron, Nova, Palmyra, Llama. The
Bedrock panel keeps 13 vendor families; this one has 6. Bedrock remains the broad instrument.

## What was built

- **`pilot.TOGETHER_SUBJECT_MODELS`** — 13 subjects, exact Together serverless API strings.
- **`pilot.TOGETHER_JUDGE_MODEL`** = `Qwen/Qwen3.7-Max`, held out of the subject list so the
  judge cannot grade itself. Mirrors the Bedrock qwen3-235b arrangement. The floor gate still
  runs, so an unproven judge aborts before any card is written.
- **`get_provider("together")`** and **`get_provider("groq")`** — OpenAI-compatible presets,
  bearer auth, key from env only, never CLI or disk.
- **`model-familiarity panel-check --provider {bedrock,together}`** — reads one endpoint
  (`/v1/models`), no completions, no cost. Reports every panel model present or MISSING and
  exits non-zero on drift.
- **Bug fix**: `OpenAICompatProvider.list_models()` and `.is_available()` never sent the
  `Authorization` header. Every hosted provider (Together, Groq, Anthropic) 401s on an
  unauthenticated `/models`, and the bare `except` swallowed it into `[]`, which reads as
  "provider has no models" rather than "you forgot the key". Both now use a shared
  `_headers()`. This was pre-existing and would have made `panel-check` useless.

Verified: `209 passed`, `ruff: All checks passed`, Bedrock panel still 32, judge not in
subjects, keyless `panel-check` fails with a clear message instead of crashing.

## Catalog drift is the standing risk

Together rotates its catalog faster than Bedrock. The model strings here were read from
`docs.together.ai/docs/serverless-models` on 2026-08-04 and are **not yet confirmed against
the live API** (no key on this machine). Run before every study:

```bash
model-familiarity panel-check --provider together
```

Anything MISSING gets dropped and the study re-registered. Never substitute a neighbouring
version.

## Blocked on: a Together API key

There is no `TOGETHER_API_KEY` in the keychain. Mint one at api.together.ai, then, using the
interactive hidden prompt so the value never lands in shell history or a file:

```bash
security add-generic-password -s TOGETHER_API_KEY -a "$USER" -U -w
export TOGETHER_API_KEY=$(security find-generic-password -s TOGETHER_API_KEY -w)
model-familiarity panel-check --provider together
```

## Note on the Groq live check

`GROQ_API_KEY` **is** in the keychain, but the kernel guard blocks reading a keychain secret
and making a network call in the same command (extract-and-send is the exfiltration shape it
watches for). The block is correct and was not worked around, so the Groq path is wired and
unit-checked but **not yet proven against the live API**. To prove it:

```bash
export GROQ_API_KEY=$(security find-generic-password -s GROQ_API_KEY -w)
python -c "import asyncio;from model_familiarity.providers import get_provider;print(asyncio.run(get_provider('groq').list_models()))"
```

## Cost expectation

Panel of 13 subjects. Together output pricing spans $0.20/M (gpt-oss-20b) to $15/M (Kimi K3),
so **run cost is dominated by Kimi K3 and GLM-5.2**. The existing `CostGuardProvider` ceiling
applies; set it deliberately before the first full sweep rather than discovering the number
afterwards.
