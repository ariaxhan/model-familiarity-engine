# Release process

PyPI is the intended primary package registry. Before the first publish, create a pending
Trusted Publisher for the as-yet-uncreated `model-familiarity-engine` PyPI project. Publishing
uses GitHub Actions Trusted Publishing with OIDC; no long-lived PyPI token is stored in
repository secrets.

1. Update the version in `pyproject.toml`, `src/model_familiarity/__init__.py`,
   `CITATION.cff`, and `CHANGELOG.md`.
2. Run `pytest`, `ruff check .`, and a fresh wheel installation test.
3. Commit the release as one logical change.
4. Create an annotated tag: `git tag -a v0.2.0 -m "v0.2.0"`.
5. Push the branch and tag. The tag workflow tests, builds one wheel and source distribution,
   creates a matching GitHub release from those exact artifacts, and separately publishes them
   from the protected `pypi` environment once Trusted Publishing is configured.
6. Verify the PyPI page, GitHub release, artifacts, README, license, and citation metadata.

Repository setup required before the first publish:

- create a protected GitHub environment named `pypi` with required reviewers;
- create a pending Trusted Publisher for the as-yet-uncreated PyPI project, bound to this
  repository, workflow `.github/workflows/release.yml`, and environment `pypi`;
- do not add a PyPI API token to GitHub secrets.

Recommended GitHub topics: `llm-evaluation`, `model-behavior`, `conversational-ai`,
`benchmarking`, `model-cards`, `python`, and `reproducible-research`.
