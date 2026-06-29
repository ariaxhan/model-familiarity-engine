# Contributing

Model Familiarity Engine is the replay/model-card layer. It is not the benchmark
suite; benchmark tests and benchmark CLI behavior belong in `llm-bench`.

Good contributions here:

- replay task ingestion
- redaction checks
- judge floor probes
- model-card rendering
- routing/export formats
- provider support needed by replay runs

Keep public samples synthetic or intentionally released. Do not commit private work
logs, raw transcripts, credentials, local cloud account details, or agent handoff
notes.

Before opening a PR:

```bash
pytest
ruff check .
```
