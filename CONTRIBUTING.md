# Contributing

Contributions should strengthen the evaluation instrument or its reproducibility: challenge
schemas, redaction, judge validation, calibration gates, offline study planning, provider
adapters, aggregate reporting, or tests.

Do not commit private work logs, raw transcripts, reasoning traces, calibration answer keys,
credentials, cloud account details, local paths, internal handoffs, or unreviewed model ranks.
New public challenges must be genericized and have a known outcome, registered trap, and
deterministic calibration spine.

Before opening a pull request:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
python -m build
```

Changes to a protocol-bearing field must change `protocol_hash()`. Add a regression test when
introducing a new field or evaluator behavior.
