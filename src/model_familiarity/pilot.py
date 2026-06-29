"""Replay-bootstrap pilot — the smallest honest loop, run end to end.

floor-gate the judge -> replay known-outcome tasks through N models (cold + guided)
-> judge each against the objective outcome -> render Model Cards from recorded observations.

Run: ``AWS_PROFILE=your-profile python -m model_familiarity.pilot``

The floor gate is hard: if the judge fails its live floor test, the run aborts before
producing any card. A card built on an unproven judge is worse than no card.
"""

from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path

from model_familiarity.card import (
    Observation,
    build_card,
    render_comparison,
)
from model_familiarity.floor import run_floor
from model_familiarity.judge import DEFAULT_JUDGE_MODEL, judge
from model_familiarity.providers import get_provider
from model_familiarity.replay import CONDITIONS, replay_task
from model_familiarity.tasks import load_tasks

# 32 non-Claude Bedrock models used by the initial pilot.
# The judge (qwen.qwen3-235b-a22b-2507) is deliberately NOT a subject — it can't grade
# itself. Some ids need the `us.` inference-profile prefix to invoke (Llama/Nova/Palmyra).
SUBJECT_MODELS = [
    # DeepSeek
    "deepseek.v3.2",
    "us.deepseek.r1-v1:0",
    # MiniMax
    "minimax.minimax-m2",
    "minimax.minimax-m2.1",
    "minimax.minimax-m2.5",
    # Mistral
    "mistral.mistral-large-3-675b-instruct",
    "mistral.devstral-2-123b",
    "mistral.magistral-small-2509",
    "mistral.ministral-3-14b-instruct",
    # Moonshot
    "moonshotai.kimi-k2.5",
    "moonshot.kimi-k2-thinking",
    # OpenAI (open weights)
    "openai.gpt-oss-120b-1:0",
    "openai.gpt-oss-20b-1:0",
    # Qwen (judge family, but distinct models; floor-test guards affinity)
    "qwen.qwen3-32b-v1:0",
    "qwen.qwen3-next-80b-a3b",
    "qwen.qwen3-coder-480b-a35b-v1:0",
    "qwen.qwen3-coder-30b-a3b-v1:0",
    # Z.AI / GLM
    "zai.glm-4.7-flash",
    "zai.glm-4.7",
    "zai.glm-5",
    # Google Gemma
    "google.gemma-3-27b-it",
    "google.gemma-3-12b-it",
    # Meta Llama
    "us.meta.llama4-maverick-17b-instruct-v1:0",
    "us.meta.llama4-scout-17b-instruct-v1:0",
    "us.meta.llama3-3-70b-instruct-v1:0",
    # NVIDIA Nemotron
    "nvidia.nemotron-super-3-120b",
    "nvidia.nemotron-nano-3-30b",
    "nvidia.nemotron-nano-12b-v2",
    "nvidia.nemotron-nano-9b-v2",
    # Amazon Nova
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    # Writer
    "us.writer.palmyra-x5-v1:0",
]
OUT_DIR = Path(__file__).resolve().parents[2] / "results" / "familiarity"


async def run_pilot(
    subjects: list[str] | None = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    concurrency: int = 6,
):
    subjects = subjects or SUBJECT_MODELS
    provider = get_provider("bedrock")
    today = datetime.date.today().isoformat()

    # --- HARD GATE: prove the judge before trusting any verdict ---
    print("floor-testing judge:", judge_model)
    floor_ok, floor_results = await run_floor(provider, judge_model)
    for r in floor_results:
        print(f"  {r.task_id:10} {r.kind:13} reached={r.reached} {r.divergence:11} "
              f"{'PASS' if r.passed else 'FAIL'}")
    if not floor_ok:
        raise SystemExit("JUDGE FAILED FLOOR — aborting. (commission -> canon/failures/)")
    print("floor: PASS\n")

    # --- replay x judge -> observations ---
    tasks = load_tasks()
    observations: list[Observation] = []
    replays_dump: list[dict] = []
    verdicts_dump: list[dict] = []

    errors: list[dict] = []
    # Bounded concurrency: cells are independent, so run several at once. The semaphore
    # caps in-flight Bedrock calls (provider has adaptive retries for throttling). Per-cell
    # try/except keeps one model's timeout/throttle from aborting the whole sweep.
    sem = asyncio.Semaphore(concurrency)
    cells = [(m, t, c) for m in subjects for t in tasks for c in CONDITIONS]

    async def run_cell(model: str, task, condition: str):
        async with sem:
            try:
                # 12000 max_tokens gives reasoning models room (4096 left them empty).
                rep = await replay_task(task, provider, model, condition, max_tokens=12000)
                v = await judge(task, rep.output, provider, judge_model=judge_model)
            except Exception as e:  # noqa: BLE001 — record + continue, never abort the sweep
                print(f"{model:42} {task.task_id:10} {condition:7} ERROR {type(e).__name__}")
                return ("err", model, task, condition, f"{type(e).__name__}: {e}")
            flag = "" if v.agrees_with_spine else "  ⚠ spine-disagree"
            print(f"{model:42} {task.task_id:10} {condition:7} "
                  f"reached={str(v.reached):5} {v.divergence:11}{flag}")
            return ("ok", model, task, condition, rep, v)

    cell_results = await asyncio.gather(*[run_cell(m, t, c) for m, t, c in cells])

    for res in cell_results:
        if res[0] == "err":
            _, model, task, condition, err = res
            errors.append({"model": model, "task": task.task_id,
                           "condition": condition, "error": err})
            continue
        _, model, task, condition, rep, v = res
        observations.append(
            Observation(
                task_id=task.task_id,
                capability=task.capability,
                model=model,
                condition=condition,
                reached=v.reached,
                divergence=v.divergence,
                how=v.how,
                latency_ms=rep.latency_ms,
                cost_usd=rep.cost_usd,
                agrees_with_spine=v.agrees_with_spine,
                answered=bool(rep.output and rep.output.strip()),
            )
        )
        replays_dump.append(rep.to_dict())
        verdicts_dump.append(v.to_dict())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "observations.json").write_text(
        json.dumps([o.to_dict() for o in observations], indent=2)
    )
    (OUT_DIR / "replays.json").write_text(json.dumps(replays_dump, indent=2))
    (OUT_DIR / "verdicts.json").write_text(json.dumps(verdicts_dump, indent=2))
    if errors:
        (OUT_DIR / "errors.json").write_text(json.dumps(errors, indent=2))
        print(f"\n{len(errors)} cell(s) errored (recorded in errors.json):")
        for e in errors:
            print(f"  {e['model']} {e['task']}/{e['condition']}: {e['error'][:80]}")

    # --- structured (.json) card per subject that produced at least one observation ---
    print()
    models_with_obs = {o.model for o in observations}
    for model in subjects:
        if model not in models_with_obs:
            continue
        card = build_card(model, observations, today)
        safe = model.replace(".", "_").replace(":", "_").replace("/", "_")
        (OUT_DIR / f"card-{safe}.json").write_text(json.dumps(card, indent=2))

    # cross-model comparison leaderboard (quick table)
    comparison = render_comparison(observations, today)
    (OUT_DIR / "comparison.md").write_text(comparison)
    print(comparison)

    # detailed quote-backed cards (.md) + cross-model report, rendered from the dumps
    # we just wrote (report reads observations.json + replays.json off disk).
    from model_familiarity import report

    report.main([])
    print(f"\nwrote {len(models_with_obs)} cards + comparison + detailed report to {OUT_DIR}")


def main():
    asyncio.run(run_pilot())


if __name__ == "__main__":
    main()
