"""Model Card renderer — a teammate profile built from observations, not a score.

Every line on the card traces to >=1 real observation (commission O4). The card is
honest about n: a 3-task pilot is explicitly labelled low-confidence, role signals are
phrased as signals (not verdicts), and claims the data can't support (e.g. best
pairings, which need multi-model co-runs) say so rather than inventing a number.
"""

from __future__ import annotations

from dataclasses import dataclass

# capability -> the role that capability is evidence for (tentative, pilot-level)
_ROLE_HINTS = {
    "mobile-web debugging (iOS WKWebView)": "debugger / implementer (mobile front-end)",
    "CSS layout / aspect-ratio debugging": "debugger / implementer (CSS layout)",
    "payments-logic / API-semantics debugging": "debugger / reviewer (API + business logic)",
}


@dataclass
class Observation:
    task_id: str
    capability: str
    model: str
    condition: str
    reached: bool | None
    divergence: str
    how: str
    latency_ms: float
    cost_usd: float | None
    agrees_with_spine: bool
    answered: bool = True  # False = model produced no answer text (e.g. reasoning overflow)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def build_card(model: str, obs: list[Observation], date: str) -> dict:
    mine = [o for o in obs if o.model == model]
    n = len(mine)
    reached = [o for o in mine if o.reached]
    by_cond = {}
    for cond in ("cold", "guided"):
        c = [o for o in mine if o.condition == cond]
        by_cond[cond] = {
            "reached": sum(1 for o in c if o.reached),
            "total": len(c),
        }

    divergence_counts: dict[str, int] = {}
    for o in mine:
        divergence_counts[o.divergence] = divergence_counts.get(o.divergence, 0) + 1

    # per-capability: reached if reached in ANY condition; cite the task
    caps: dict[str, dict] = {}
    for o in mine:
        d = caps.setdefault(
            o.capability, {"task_id": o.task_id, "reached_any": False, "divergences": []}
        )
        d["reached_any"] = d["reached_any"] or bool(o.reached)
        d["divergences"].append(f"{o.condition}:{o.divergence}")

    strengths = [cap for cap, d in caps.items() if d["reached_any"]]
    weaknesses = [cap for cap, d in caps.items() if not d["reached_any"]]

    failure_modes = [
        {"task_id": o.task_id, "capability": o.capability, "condition": o.condition, "how": o.how}
        for o in mine
        if not o.reached or o.divergence == "worse"
    ]

    roles = sorted({_ROLE_HINTS.get(cap, cap) for cap in strengths})

    lat = [o.latency_ms for o in mine if o.latency_ms]
    costs = [o.cost_usd for o in mine if o.cost_usd is not None]
    spine_disagree = [o for o in mine if not o.agrees_with_spine]

    return {
        "model": model,
        "n": n,
        "date": date,
        "reached_rate": f"{len(reached)}/{n}",
        "by_condition": by_cond,
        "divergence_counts": divergence_counts,
        "capabilities": caps,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "roles_signal": roles,
        "failure_modes": failure_modes,
        "avg_latency_ms": round(sum(lat) / len(lat), 1) if lat else None,
        "avg_cost_usd": (sum(costs) / len(costs)) if costs else None,
        "cost_known": len(costs) > 0,
        "spine_disagreements": len(spine_disagree),
        "confidence": f"Low (pilot, n={n} observations across {len(caps)} task types)",
    }


def render_card_md(card: dict) -> str:
    m = card
    lines = [
        f"# Model Card — {m['model']}",
        "",
        f"> Confidence: **{m['confidence']}** · generated {m['date']}",
        "> Replay bootstrap (cold + guided). Every line traces to an observation below.",
        "",
        "## At a glance",
        f"- **Outcome reached:** {m['reached_rate']} observations",
        f"  - cold: {m['by_condition']['cold']['reached']}/{m['by_condition']['cold']['total']}"
        f" · guided: {m['by_condition']['guided']['reached']}"
        f"/{m['by_condition']['guided']['total']}",
        f"- **Divergence mix:** {m['divergence_counts']}",
    ]
    if m["avg_latency_ms"] is not None:
        lines.append(f"- **Avg latency:** {m['avg_latency_ms']} ms")
    if m["cost_known"]:
        lines.append(f"- **Avg cost/task:** ${m['avg_cost_usd']:.6f}")
    else:
        lines.append("- **Avg cost/task:** unknown (no public pricing recorded — not fabricated)")
    if m["spine_disagreements"]:
        lines.append(
            f"- ⚠️ **Judge/spine disagreements:** {m['spine_disagreements']} "
            "(surfaced, not hidden — see observations)"
        )

    lines += [
        "",
        "## Role signal (tentative — pilot n)",
    ]
    lines += [f"- {r}" for r in m["roles_signal"]] or ["- (no role reached threshold)"]

    lines += ["", "## Strengths (reached the outcome)"]
    if m["strengths"]:
        for cap in m["strengths"]:
            d = m["capabilities"][cap]
            lines.append(f"- **{cap}** ({d['task_id']}) — {', '.join(d['divergences'])}")
    else:
        lines.append("- none reached")

    lines += ["", "## Failure modes"]
    if m["failure_modes"]:
        for f in m["failure_modes"]:
            lines.append(f"- **{f['capability']}** ({f['task_id']}, {f['condition']}): {f['how']}")
    else:
        lines.append("- none observed in this pilot")

    lines += [
        "",
        "## Best pairings",
        "- Insufficient data — pairings need multi-model co-runs (phase 2). Not inferred.",
        "",
        "## Provenance",
        f"- n = {m['n']} observations (3 real mined tasks x 2 conditions).",
        "- Outcomes judged by an LLM judge anchored to the objective outcome, "
        "floor-tested live (garbage -> not-reached; differently-worded-correct -> reached).",
        "- Pilot != powered. Trust resets on model version change.",
    ]
    return "\n".join(lines)


def render_comparison(obs: list[Observation], date: str) -> str:
    """Cross-model leaderboard from observations. Ranked by outcomes reached, then cost.

    Honest: every cell is an n=1 observation; the cold/guided split and per-task columns
    show *where* a model reached, not a powered score. Spine disagreements are shown
    (they were judge-corrected spine errors in this pilot).
    """
    models = sorted({o.model for o in obs})
    tasks = sorted({o.task_id for o in obs})
    rows = []
    for model in models:
        mine = [o for o in obs if o.model == model]
        reached = sum(1 for o in mine if o.reached)
        cold = sum(1 for o in mine if o.condition == "cold" and o.reached)
        guided = sum(1 for o in mine if o.condition == "guided" and o.reached)
        per_task = {}
        for t in tasks:
            cell = [o for o in mine if o.task_id == t]
            r = sum(1 for o in cell if o.reached)
            per_task[t] = f"{r}/{len(cell)}"
        costs = [o.cost_usd for o in mine if o.cost_usd is not None]
        lats = [o.latency_ms for o in mine if o.latency_ms]
        disagree = sum(1 for o in mine if not o.agrees_with_spine)
        no_answer = sum(1 for o in mine if not o.answered)
        rows.append(
            {
                "model": model,
                "reached": reached,
                "total": len(mine),
                "cold": cold,
                "guided": guided,
                "per_task": per_task,
                "cost": (sum(costs) / len(costs)) if costs else None,
                "lat": (sum(lats) / len(lats)) if lats else None,
                "disagree": disagree,
                "no_answer": no_answer,
            }
        )
    rows.sort(key=lambda r: (-r["reached"], r["cost"] if r["cost"] is not None else 9e9))

    short = {t: t[:10] for t in tasks}
    head = ["model", "reached", "cold", "guided", *[short[t] for t in tasks],
            "no-ans", "cost/task", "lat ms"]
    lines = [
        "# Model Familiarity — cross-model comparison",
        "",
        f"> {len(models)} models · 3 known-outcome replay tasks · cold + guided · generated {date}",
        "> Ranked by outcomes reached, then cost. Every cell is n=1 — pilot, not powered.",
        "",
        "| " + " | ".join(head) + " |",
        "|" + "|".join(["---"] * len(head)) + "|",
    ]
    for r in rows:
        cost = f"${r['cost']:.5f}" if r["cost"] is not None else "n/a"
        lat = f"{r['lat']:.0f}" if r["lat"] is not None else "n/a"
        cells = [
            f"`{r['model']}`",
            f"**{r['reached']}/{r['total']}**",
            str(r["cold"]),
            str(r["guided"]),
            *[r["per_task"][t] for t in tasks],
            str(r["no_answer"]) if r["no_answer"] else "·",
            cost,
            lat,
        ]
        lines.append("| " + " | ".join(cells) + " |")

    lines += [
        "",
        f"_Tasks: {', '.join(f'{short[t]} = {t}' for t in tasks)}._",
        "_cold = outcomes reached with no help; guided = reached after a realistic "
        "frustrated follow-up. **no-ans** = cells where the model emitted NO answer (e.g. a "
        "reasoning model overflowing its token budget) — these count as not-reached but are "
        "a budget/behaviour artifact, not a wrong diagnosis. cost/task n/a = no public "
        "pricing recorded (not fabricated)._",
    ]
    return "\n".join(lines)
