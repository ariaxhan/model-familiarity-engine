"""Detailed Model Card + report renderer — built from saved replay data, no re-run.

The pilot sweep (``pilot.py``) is the expensive part: it calls Bedrock and dumps
``replays.json`` (full model outputs) and ``observations.json`` (the joined record with
the judge's verdict + rationale per cell). This module is the *cheap* part: it reads
those files off disk and renders rich, quote-backed Model Cards + a cross-model report —
so the card format can be iterated freely without spending another token.

What makes these cards "detailed" (vs the at-a-glance ``card.py``):

- **Direct quotes** — every per-task verdict carries a real snippet from the model's
  own output (the diagnosis lede), so the card shows *how it talked*, not just whether
  it was right.
- **Signature quirks** — evidence-anchored behavioural tics (verbosity, option-spraying,
  hedging, hidden-reasoning load, cold->guided dynamics). Each quirk line cites the number
  it was derived from. No vibes: if a quirk can't point at a count, it isn't printed.
- **Task-by-task transcript-lite** — cold + guided side by side per task, with the judge's
  one-line rationale and a quote.

Run (after a sweep): ``python -m model_familiarity.report [model ...]``
With no args it renders every model that has observations; with args it renders just
those (the "selected N" featured set).
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path
from statistics import median

OUT_DIR = Path(__file__).resolve().parents[2] / "results" / "familiarity"

_TASK_TITLE = {
    "ios_zoom": "iOS WKWebView auto-zoom (mobile-web)",
    "cover_crop": "aspect-ratio crop (CSS layout)",
    "annual_price": "per-month price bug (payments logic)",
}


# --------------------------------------------------------------------------- io
def _load() -> tuple[list[dict], list[dict]]:
    obs = json.loads((OUT_DIR / "observations.json").read_text())
    reps = json.loads((OUT_DIR / "replays.json").read_text())
    return obs, reps


def _safe(model: str) -> str:
    return model.replace(".", "_").replace(":", "_").replace("/", "_")


# ------------------------------------------------------------------- text utils
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MD_NOISE = re.compile(r"^[#>*\-\s]+|[*_`]")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _lede(output: str, max_len: int = 260) -> str:
    """First substantive prose sentence(s) of an answer — the diagnosis lede.

    Strips code fences and markdown chrome so the quote reads as the model's actual
    voice, not a header or a code block.
    """
    if not output or not output.strip():
        return "_(no answer — model emitted empty content)_"
    body = _FENCE.sub(" ", output)
    for raw in body.split("\n"):
        line = _MD_NOISE.sub("", raw).strip()
        if len(line) < 25:  # skip headers, list bullets, stubs
            continue
        sents = _SENT_SPLIT.split(line)
        quote = sents[0].strip()
        if len(quote) < 25 and len(sents) > 1:
            quote = (quote + " " + sents[1]).strip()
        if len(quote) > max_len:
            quote = quote[:max_len].rsplit(" ", 1)[0] + "…"
        return quote
    flat = re.sub(r"\s+", " ", body).strip()
    return (flat[:max_len] + "…") if len(flat) > max_len else flat


def _count_options(output: str) -> int:
    """How many distinct fixes the model enumerated (option/solution/fix/approach N)."""
    o = output.lower()
    labelled = len(re.findall(r"(?:option|solution|approach|fix|method)\s*#?\s*\d", o))
    numbered_headers = len(re.findall(r"^\s{0,3}#{1,4}\s*\d+[.)]", output, re.MULTILINE))
    return max(labelled, numbered_headers)


_HEDGES = ("might", "may ", "could ", "possibly", "perhaps", "i think", "not sure",
           "it depends", "in some cases", "likely", "probably")


def _count_hedges(output: str) -> int:
    o = output.lower()
    return sum(o.count(h) for h in _HEDGES)


def _has_emoji(output: str) -> bool:
    return bool(re.search(r"[\U0001F000-\U0001FAFF☀-➿]", output))


# ------------------------------------------------------------------ per-model
def _model_rows(model: str, obs, reps):
    o = [x for x in obs if x["model"] == model]
    r = [x for x in reps if x["model"] == model]
    rep_by = {(x["task_id"], x["condition"]): x for x in r}
    return o, r, rep_by


def _quirks(o, r, roster_median_tokens: float) -> list[str]:
    """Evidence-anchored behavioural notes. Each line cites the number it came from."""
    q: list[str] = []
    answered_reps = [x for x in r if x["output"] and x["output"].strip()]
    toks = [x["output_tokens"] for x in r if x.get("output_tokens")]
    med_tok = median(toks) if toks else 0

    if med_tok and roster_median_tokens:
        ratio = med_tok / roster_median_tokens
        if ratio >= 1.6:
            q.append(f"**Verbose** — median {med_tok:.0f} output tokens/answer, "
                     f"{ratio:.1f}× the roster median ({roster_median_tokens:.0f}).")
        elif ratio <= 0.6:
            q.append(f"**Terse** — median {med_tok:.0f} output tokens/answer, "
                     f"{ratio:.1f}× the roster median ({roster_median_tokens:.0f}).")

    rchars = [x["reasoning_chars"] for x in r if x.get("reasoning_chars")]
    if rchars:
        avg_r = sum(rchars) / len(rchars)
        q.append(f"**Thinks out loud (hidden)** — emits a reasoning block on "
                 f"{len(rchars)}/{len(r)} cells, avg {avg_r:.0f} chars of scratchpad "
                 "the judge never sees.")

    opt_counts = [_count_options(x["output"]) for x in answered_reps]
    if opt_counts:
        max_opt = max(opt_counts)
        avg_opt = sum(opt_counts) / len(opt_counts)
        if max_opt >= 4:
            q.append(f"**Sprays options** — listed up to {max_opt} separate fixes in one "
                     f"answer (avg {avg_opt:.1f}/answer); offers a menu rather than committing.")
        elif avg_opt < 1.2:
            q.append("**Commits to one fix** — rarely enumerates alternatives "
                     f"(avg {avg_opt:.1f} option blocks/answer).")

    hedges = [_count_hedges(x["output"]) for x in answered_reps]
    if hedges and sum(hedges) / len(hedges) >= 4:
        q.append(f"**Hedges** — avg {sum(hedges) / len(hedges):.1f} hedge words/answer "
                 "(might/could/possibly/depends).")

    if answered_reps and all(_has_emoji(x["output"]) for x in answered_reps):
        q.append("**Decorates** — uses emoji/symbols in every answer.")

    blanks = [x for x in o if not x.get("answered", True)]
    if blanks:
        cells = ", ".join(f"{b['task_id']}/{b['condition']}" for b in blanks)
        q.append(f"**Overflow risk** — emitted NO answer on {len(blanks)} cell(s) "
                 f"({cells}); reasoning likely ate the token budget.")

    reached = {(x["task_id"], x["condition"]): x["reached"] for x in o}
    tasks = sorted({x["task_id"] for x in o})
    self_correct, regress = [], []
    for t in tasks:
        c, g = reached.get((t, "cold")), reached.get((t, "guided"))
        if c is False and g is True:
            self_correct.append(t)
        if c is True and g is False:
            regress.append(t)
    if self_correct:
        q.append("**Recovers on a nudge** — flipped wrong→right after the bare "
                 f"\"still broken\" follow-up on: {', '.join(self_correct)}.")
    if regress:
        q.append("**Regresses on a nudge** — flipped right→wrong once pushed on: "
                 f"{', '.join(regress)} (the vague follow-up made it worse).")

    return q


def render_detailed_card(model: str, obs, reps, roster_median_tokens, date) -> str:
    o, r, rep_by = _model_rows(model, obs, reps)
    n = len(o)
    if n == 0:
        return f"# Model Card — {model}\n\n_No observations recorded (all cells errored)._\n"

    reached = sum(1 for x in o if x["reached"])
    cold = [x for x in o if x["condition"] == "cold"]
    guided = [x for x in o if x["condition"] == "guided"]
    cold_r = sum(1 for x in cold if x["reached"])
    guided_r = sum(1 for x in guided if x["reached"])
    lats = [x["latency_ms"] for x in o if x.get("latency_ms")]
    costs = [x["cost_usd"] for x in o if x.get("cost_usd") is not None]
    toks = [x["output_tokens"] for x in r if x.get("output_tokens")]
    disagree = sum(1 for x in o if not x.get("agrees_with_spine", True))

    lines = [
        f"# Model Card — `{model}`",
        "",
        f"> **Outcome reached: {reached}/{n}** "
        f"(cold {cold_r}/{len(cold)} · guided {guided_r}/{len(guided)}) · "
        f"confidence **Low** (pilot, n={n}) · generated {date}",
        "> Detailed replay profile. Every quote below is the model's own output, verbatim.",
        "",
        "## At a glance",
        f"- **Reached the root cause:** {reached}/{n} cells",
        f"- **Cold vs guided:** {cold_r}/{len(cold)} unaided · {guided_r}/{len(guided)} "
        "after a bare \"still broken\" follow-up",
    ]
    if lats:
        lines.append(f"- **Latency:** {median(lats):.0f} ms median "
                     f"({min(lats):.0f}–{max(lats):.0f})")
    if toks:
        lines.append(f"- **Answer length:** {median(toks):.0f} output tokens median")
    if costs:
        lines.append(f"- **Cost/task:** ${sum(costs) / len(costs):.6f} avg")
    else:
        lines.append("- **Cost/task:** unknown (no public pricing recorded — not fabricated)")
    if disagree:
        lines.append(f"- ⚠️ **Judge/spine disagreements:** {disagree} (surfaced, not hidden)")

    lines += ["", "## Signature quirks",
              "_Behavioural tics, each anchored to a count from the runs._", ""]
    quirks = _quirks(o, r, roster_median_tokens)
    lines += [f"- {q}" for q in quirks] if quirks else \
        ["- _Nothing distinctive enough to flag at this n._"]

    lines += ["", "## Task by task"]
    tasks = sorted({x["task_id"] for x in o})
    for t in tasks:
        lines += ["", f"### {_TASK_TITLE.get(t, t)}"]
        for cond in ("cold", "guided"):
            ob = next((x for x in o if x["task_id"] == t and x["condition"] == cond), None)
            if ob is None:
                lines.append(f"- **{cond}:** _no data (cell errored)_")
                continue
            mark = "✅ reached" if ob["reached"] else "❌ missed"
            div = ob.get("divergence", "")
            how = (ob.get("how") or "").strip()
            if len(how) > 300:
                how = how[:300].rsplit(" ", 1)[0] + "…"
            rep = rep_by.get((t, cond))
            quote = _lede(rep["output"]) if rep else "_(output not saved)_"
            lines.append(f"- **{cond}** — {mark} ({div}). {how}")
            lines.append(f"  > {quote}")

    fails = [x for x in o if not x["reached"] or x.get("divergence") == "worse"]
    lines += ["", "## Failure modes"]
    if fails:
        for f in fails:
            how = (f.get("how") or "").strip()
            if len(how) > 240:
                how = how[:240].rsplit(" ", 1)[0] + "…"
            lines.append(f"- **{f['task_id']} / {f['condition']}** ({f.get('divergence')}): {how}")
    else:
        lines.append("- None — reached every cell in this pilot.")

    lines += [
        "",
        "## Provenance",
        f"- n = {n} cells (3 real mined bugs × cold/guided). Pilot, not powered.",
        "- Outcomes judged by an LLM judge anchored to the objective root cause, "
        "floor-tested live before the run (garbage→missed, differently-worded-correct→reached).",
        "- Quirks are computed deterministically from the saved outputs (token counts, "
        "regex tallies, cold↔guided flips) — no LLM-as-judge in the quirk layer.",
        "- Trust resets on any model-version change.",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------- cross-model report
def render_report(selected: list[str], obs, reps, date) -> str:
    models = [m for m in selected if any(x["model"] == m for x in obs)]
    tasks = sorted({x["task_id"] for x in obs})

    def stats(m):
        o = [x for x in obs if x["model"] == m]
        return {
            "reached": sum(1 for x in o if x["reached"]),
            "n": len(o),
            "cold": sum(1 for x in o if x["condition"] == "cold" and x["reached"]),
            "guided": sum(1 for x in o if x["condition"] == "guided" and x["reached"]),
            "blanks": sum(1 for x in o if not x.get("answered", True)),
        }

    ranked = sorted(models, key=lambda m: -stats(m)["reached"])

    # per-model derived metrics for the standouts section (all anchored to data)
    def metrics(m):
        o = [x for x in obs if x["model"] == m]
        r = [x for x in reps if x["model"] == m]
        toks = [x["output_tokens"] for x in r if x.get("output_tokens")]
        lats = [x["latency_ms"] for x in o if x.get("latency_ms")]
        rchars = [x["reasoning_chars"] for x in r if x.get("reasoning_chars")]
        reached = {(x["task_id"], x["condition"]): x["reached"] for x in o}
        flips = sum(1 for t in tasks
                    if reached.get((t, "cold")) != reached.get((t, "guided")))
        return {
            "tok": median(toks) if toks else 0,
            "lat": median(lats) if lats else 0,
            "reason": (sum(rchars) / len(rchars)) if rchars else 0,
            "flips": flips,
            "reached": stats(m)["reached"],
        }

    met = {m: metrics(m) for m in models}

    lines = [
        "# Model Familiarity — detailed report",
        "",
        f"> {len(models)} selected models · 3 known-outcome replay tasks · "
        f"cold + guided · generated {date}",
        "> Bedrock-only. Cold = no help; guided = a deliberately content-free \"its still "
        "not working, just fix it\" follow-up (tests recovery from pure frustration, not a hint).",
        "",
        "## Leaderboard",
        "",
        "| model | reached | cold | guided | overflow |",
        "|---|---|---|---|---|",
    ]
    for m in ranked:
        s = stats(m)
        lines.append(f"| `{m}` | **{s['reached']}/{s['n']}** | {s['cold']}/3 | {s['guided']}/3 | "
                     f"{s['blanks'] or '·'} |")

    # --- standouts: auto-featured, each line cites the number behind it ---
    lines += ["", "## Standouts"]
    if models:
        top = max(models, key=lambda m: met[m]["reached"])
        lines.append(f"- 🏆 **Strongest:** `{top}` — reached {met[top]['reached']}/6.")
        mover = max(models, key=lambda m: met[m]["flips"])
        if met[mover]["flips"]:
            lines.append(f"- 🔁 **Most follow-up-sensitive:** `{mover}` — "
                         f"{met[mover]['flips']} of 3 tasks flipped between cold and guided.")
        wordy = max(models, key=lambda m: met[m]["tok"])
        terse = min(models, key=lambda m: met[m]["tok"] or 9e9)
        lines.append(f"- 📣 **Most verbose:** `{wordy}` ({met[wordy]['tok']:.0f} tok median) · "
                     f"**most terse:** `{terse}` ({met[terse]['tok']:.0f} tok).")
        reasoners = [m for m in models if met[m]["reason"]]
        if reasoners:
            deep = max(reasoners, key=lambda m: met[m]["reason"])
            lines.append(f"- 🧠 **Heaviest hidden reasoner:** `{deep}` — "
                         f"avg {met[deep]['reason']:.0f} chars of scratchpad/answer.")
        fast = min((m for m in models if met[m]["lat"]),
                   key=lambda m: met[m]["lat"], default=None)
        if fast:
            lines.append(f"- ⚡ **Fastest:** `{fast}` — {met[fast]['lat']:.0f} ms median latency.")
        overflowers = [m for m in models if stats(m)["blanks"]]
        if overflowers:
            lines.append("- 💥 **Choked (empty answers):** "
                         + ", ".join(f"`{m}`" for m in overflowers) + ".")

    lines += ["", "## By task — who reached the root cause"]
    for t in tasks:
        lines += ["", f"### {_TASK_TITLE.get(t, t)}"]
        got = [m for m in models if any(
            x["model"] == m and x["task_id"] == t and x["reached"] for x in obs)]
        missed = [m for m in models if m not in got]
        lines.append(f"- **Reached ({len(got)}/{len(models)}):** "
                     + (", ".join(f"`{m}`" for m in got) or "none"))
        lines.append("- **Missed:** " + (", ".join(f"`{m}`" for m in missed) or "none"))

    lines += ["", "## Field notes"]
    movers = []
    for m in models:
        o = [x for x in obs if x["model"] == m]
        reached = {(x["task_id"], x["condition"]): x["reached"] for x in o}
        flips = sum(1 for t in tasks
                    if reached.get((t, "cold")) != reached.get((t, "guided")))
        if flips:
            movers.append((m, flips))
    if movers:
        lines.append("- **Follow-up sensitivity:** " + ", ".join(
            f"`{m}` ({f} task{'s' if f > 1 else ''} flipped)" for m, f in movers)
            + " — the rest answered the bare nudge exactly as they answered cold.")
    else:
        lines.append("- **Follow-up sensitivity:** none — every model answered the vague "
                     "follow-up identically to cold (the content-free nudge moved nothing).")
    overflowers = [m for m in models if stats(m)["blanks"]]
    if overflowers:
        lines.append("- **Token-budget overflow:** " + ", ".join(f"`{m}`" for m in overflowers)
                     + " emitted empty answers on some cells (reasoning ate the budget).")

    lines += [
        "",
        "## Method",
        "- Each model got all 3 tasks × 2 conditions. Replays + judge verdicts saved to "
        "`results/familiarity/{replays,verdicts,observations}.json`.",
        "- Per-model detailed cards: `results/familiarity/card-<model>.md`.",
        "- Pilot, n=6/model. Signals, not rankings.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None):
    argv = argv if argv is not None else sys.argv[1:]
    obs, reps = _load()
    all_models = sorted({x["model"] for x in obs})
    selected = argv or all_models
    toks_all = [x["output_tokens"] for x in reps if x.get("output_tokens")]
    roster_med = median(toks_all) if toks_all else 0
    date = datetime.date.today().isoformat()

    for m in selected:
        md = render_detailed_card(m, obs, reps, roster_med, date)
        (OUT_DIR / f"card-{_safe(m)}.md").write_text(md)
    report = render_report(selected, obs, reps, date)
    (OUT_DIR / "detailed-report.md").write_text(report)
    print(f"rendered {len(selected)} detailed cards + detailed-report.md to {OUT_DIR}")
    print("selected:", ", ".join(selected))


if __name__ == "__main__":
    main()
