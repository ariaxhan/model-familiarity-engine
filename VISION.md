# Vision

Model choice should be based on earned responsibility, not vibes or a single
leaderboard score.

The engine accumulates observations about how models behave in real workflows:
whether they solve, recover, ask for evidence, overclaim, get cheaper with
guidance, or need supervision.

The core object is an Observation:

```text
Observation = model@version + role + task + workflow + outcome + regret + evidence
```

Model cards are built from observations. Routing decisions are built from model
cards. Trust decays when model versions change.

Model Familiarity Engine is not a wrapper around a benchmark. It can ingest
benchmark results as one evidence source, but its core loop is replay,
redaction, judging, model cards, and routing knowledge.
