# Model Familiarity Engine

A Model Familiarity Engine, not a leaderboard.

It continuously onboards language models by observing them in real work, learning
where they should be trusted, and building evidence-backed routing knowledge for
multi-model agent systems.

The replay-bootstrap loop is shipped: load known-outcome tasks, redact secrets,
replay through models, floor-test the judge, and render model cards from
observations.

It can import external evidence, including benchmark results, but it does not
depend on any one benchmark project.

The question is not "which model is best?"

It is:

> What responsibility has this model earned?

## Status

Bootstrap loop shipped.

## Stack

Python, Bedrock, Ollama, Claude CLI, OpenAI-compatible providers.

## Scope

- Replay bootstrap for known-outcome tasks.
- Fail-closed redaction before third-party model calls.
- Judge floor tests before any model card is trusted.
- Evidence-backed model cards from observations.
- Optional import/export paths for benchmark or routing systems.

## Quick Start

Install locally:

```bash
git clone https://github.com/ariaxhan/model-familiarity-engine
cd model-familiarity-engine
pip install -e ".[dev]"
```

Run the replay bootstrap:

```bash
export AWS_PROFILE=your-profile
export AWS_REGION=us-west-2
model-familiarity
```

The default pilot uses a tiny synthetic sample corpus in `data/sample_tasks.json`.
Replace it with your own redacted known-outcome tasks before drawing conclusions.

## How It Works

```text
past work -> redacted known-outcome tasks -> replay through models
         -> floor-tested judge -> observations -> model cards
```

Benchmarks can help, but they are not the center of the engine. The familiarity
layer asks what work a model has earned in an agent system: planner,
implementer, reviewer, debugger, summarizer, critic, or "needs human review."

## Public Data Boundary

This repo ships code and synthetic samples. Real replay corpora often come from
private work logs, so they should be redacted and stored separately unless they
were intentionally prepared for release.

## License

MIT
