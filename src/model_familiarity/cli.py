"""Safe command-line entry point for offline evaluation and guarded live replay."""

from __future__ import annotations

import asyncio
import json
from importlib.resources import files
from pathlib import Path

import click
import yaml

from model_familiarity import __version__
from model_familiarity.floor import PROBES
from model_familiarity.judge import DEFAULT_JUDGE_MODEL
from model_familiarity.pilot import run_pilot
from model_familiarity.providers import get_provider
from model_familiarity.providers.base import BaseProvider, LLMResponse, SafetyLimitError
from model_familiarity.study import load_config, render_plan, validate_config


class CostGuardProvider(BaseProvider):
    """Stops a run when observed provider-reported cost crosses the accepted ceiling."""

    def __init__(self, wrapped: BaseProvider, ceiling: float, allow_unknown: bool):
        self.wrapped = wrapped
        self.ceiling = ceiling
        self.allow_unknown = allow_unknown
        self.spent = 0.0
        self.blocked_reason: str | None = None
        self.name = f"cost-guard:{wrapped.name}"

    def _record(self, response: LLMResponse) -> LLMResponse:
        if response.cost_usd is None and not self.allow_unknown:
            self.blocked_reason = (
                "provider did not report a price; cost enforcement cannot continue"
            )
            raise SafetyLimitError(self.blocked_reason)
        self.spent += response.cost_usd or 0.0
        if self.spent > self.ceiling:
            self.blocked_reason = (
                f"observed cost ${self.spent:.4f} exceeded ceiling ${self.ceiling:.4f}"
            )
            raise SafetyLimitError(self.blocked_reason)
        return response

    def _check(self) -> None:
        if self.blocked_reason:
            raise SafetyLimitError(self.blocked_reason)

    async def complete(self, *args, **kwargs):
        self._check()
        return self._record(await self.wrapped.complete(*args, **kwargs))

    async def converse(self, *args, **kwargs):
        self._check()
        return self._record(await self.wrapped.converse(*args, **kwargs))

    async def list_models(self) -> list[str]:
        return await self.wrapped.list_models()

    async def is_available(self) -> bool:
        return await self.wrapped.is_available()


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Evaluate model behavior with provenance and instrument-health gates."""


@main.command()
@click.option("--json-output", is_flag=True, help="Print the machine-readable gate packet.")
def health(json_output: bool) -> None:
    """Show the reviewed aggregate Experiment 0 instrument-health result."""
    name = "gates.json" if json_output else "health-report.md"
    text = files("model_familiarity").joinpath("data", "exp0", name).read_text()
    if json_output:
        click.echo(json.dumps(json.loads(text), indent=2))
    else:
        click.echo(text.rstrip())


@main.group()
def study() -> None:
    """Validate or plan a preregistered study without model API calls."""


def _load_study_or_click_error(config: str) -> dict:
    try:
        return load_config(config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise click.ClickException(f"cannot read study config: {exc}") from exc


@study.command("example")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("example-behavioral-study.yaml"),
    show_default=True,
)
@click.option("--force", is_flag=True, help="Replace an existing output file.")
def study_example(output: Path, force: bool) -> None:
    """Write a package-safe behavioral-study template."""
    if output.exists() and not force:
        raise click.ClickException(f"refusing to overwrite {output}; pass --force")
    output.parent.mkdir(parents=True, exist_ok=True)
    template = files("model_familiarity").joinpath("data", "example-study.yaml").read_text()
    output.write_text(template)
    click.echo(f"wrote {output}")


@study.command("validate")
@click.argument("config", type=click.Path(exists=True, dir_okay=False))
def study_validate(config: str) -> None:
    cfg = _load_study_or_click_error(config)
    errors, warnings = validate_config(cfg)
    for warning in warnings:
        click.echo(f"WARN: {warning}")
    if errors:
        for error in errors:
            click.echo(f"ERROR: {error}")
        raise click.ClickException("study config is invalid")
    click.echo(f"OK: {cfg['study_id']} valid ({len(warnings)} warning(s))")


@study.command("plan")
@click.argument("config", type=click.Path(exists=True, dir_okay=False))
def study_plan(config: str) -> None:
    cfg = _load_study_or_click_error(config)
    errors, warnings = validate_config(cfg)
    if errors:
        raise click.ClickException("invalid config; run study validate first")
    for warning in warnings:
        click.echo(f"WARN: {warning}")
    click.echo(render_plan(cfg, config))


@main.command("run")
@click.option("--model", "models", multiple=True, required=True, help="Subject model id.")
@click.option("--judge-model", default=DEFAULT_JUDGE_MODEL, show_default=True)
@click.option("--provider", default="bedrock", show_default=True)
@click.option("--concurrency", default=1, type=click.IntRange(1, 16), show_default=True)
@click.option("--cost-ceiling-usd", type=click.FloatRange(min=0.01))
@click.option(
    "--disable-cost-enforcement-for-unknown-pricing",
    is_flag=True,
    help="Treat unpriced responses as $0; the ceiling then cannot bound their true cost.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("model-familiarity-results"),
    show_default=True,
)
@click.option("--execute", is_flag=True, help="Actually call provider APIs; default is dry-run.")
@click.option("--confirm", help="Required exact value: LIVE-RUN-WITH-BILLING")
def live_run(
    models: tuple[str, ...],
    judge_model: str,
    provider: str,
    concurrency: int,
    cost_ceiling_usd: float | None,
    disable_cost_enforcement_for_unknown_pricing: bool,
    output_dir: Path,
    execute: bool,
    confirm: str | None,
) -> None:
    tasks = 3
    conditions = 2
    floor_calls = len(PROBES)
    replay_and_judge_calls = len(models) * tasks * conditions * 2
    click.echo("LIVE RUN PLAN")
    click.echo(f"  provider ............. {provider}")
    click.echo(f"  subjects ............. {len(models)}")
    click.echo(f"  provider-call ceiling  {floor_calls + replay_and_judge_calls}")
    click.echo(f"  observed-cost ceiling  {cost_ceiling_usd if cost_ceiling_usd else 'not set'}")
    if not execute:
        click.echo("DRY RUN: no model API was called.")
        return
    if confirm != "LIVE-RUN-WITH-BILLING":
        raise click.ClickException("execution requires --confirm LIVE-RUN-WITH-BILLING")
    if cost_ceiling_usd is None:
        raise click.ClickException("execution requires --cost-ceiling-usd")
    if concurrency != 1:
        raise click.ClickException("live execution currently requires --concurrency 1 so a "
                                   "cost abort cannot leave billable calls in flight")
    if disable_cost_enforcement_for_unknown_pricing:
        click.echo(
            "WARNING: COST ENFORCEMENT IS DISABLED FOR UNKNOWN-PRICED RESPONSES; "
            "they count as $0 toward the ceiling.",
            err=True,
        )
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    wrapped = get_provider(provider)
    guarded = CostGuardProvider(
        wrapped, cost_ceiling_usd, disable_cost_enforcement_for_unknown_pricing
    )
    try:
        asyncio.run(
            run_pilot(
                subjects=list(models),
                judge_model=judge_model,
                concurrency=concurrency,
                provider=guarded,
                output_dir=output_dir,
            )
        )
    except SafetyLimitError as exc:
        raise click.ClickException(f"LIVE RUN ABORTED: {exc}") from exc
    click.echo(f"observed provider-reported cost: ${guarded.spent:.4f}")


if __name__ == "__main__":
    main()
