"""Instrument Health report, the 9-gate certification block that opens every study.

A model finding on an uncertified instrument is not a finding, it is a number with unknown
error bars. This module reads the Exp 0 shards (panel verdicts, judge test-retest, blinding,
variance, human calibration, floor gate) and scores each of the nine certification gates
against its PRE-REGISTERED threshold, then renders the health block + a verdict:

  CERTIFIED, all 9 hard gates PASS.
  CONDITIONALLY CERTIFIED, measurable gates PASS but ≥1 is PENDING (e.g. human labels not yet
                            collected) or carries a named caveat; claims ship with the caveat.
  NOT CERTIFIED, ≥1 hard gate FAILs. The study reports the instrument problem and
                            stops. A NOT-CERTIFIED that names the broken component is a
                            *successful* Exp 0.

Threshold discipline (commission): the 3 mechanically-groundable gates are LOCKED from the
pilot; the 6 panel-run gates' thresholds are fixed HERE, in code, committed BEFORE the run
produces any data, that is what "pre-registered, set before reading the results" means. No
threshold is ever moved after seeing this run's numbers.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import textwrap
from dataclasses import fields
from fractions import Fraction

from model_familiarity import layout
from model_familiarity.blinding import CANDIDATE_FAMILIES
from model_familiarity.challenges import load_challenges
from model_familiarity.lhcr_judge import _SYSTEM as JUDGE_SYSTEM
from model_familiarity.panel import DEFAULT_PANEL, EXP0_ENV_MODEL

RUBRIC_VERSION = "lhcr-rubric-v1"  # bump on any rubric/dim/schema change → re-certify

# --- PRE-REGISTERED THRESHOLDS (fixed in code before the run; never moved after) ----------
# The 3 locked gates are grounded in the recovered pilot. The 6 panel-run gates are set here,
# a-priori, with rationale, committed before the env≠judge run produces a single number.
THRESHOLDS = {
    # locked (pilot-grounded)
    "challenge_ambiguity": {"min_solve": 0.05, "max_solve": 0.95, "max_flagged": 0.10},
    "floor_gate": {"required": 1.0},
    "provenance": {"required": True},
    # panel-run (pre-registered a-priori, set before reading the run)
    "judge_reliability": {"floor": 0.71, "target": 0.80},   # must beat combined-noise floor
    "panel_agreement": {"min_reached_pair": 0.67},          # ≥ majority on the key metric
    "blind_leakage": {"max_over_chance": 0.15},             # ≈ chance within +15pp absolute
    "human_anchor": {"min_agreement": 0.70, "max_gap_below_jj": 0.10},
    "oracle_fn": {"max_fn": 0.15},                          # solved is a lower bound above this
    "oracle_consistency": {"min": 0.90},                   # identical fix → identical verdict
}

PASS, FAIL, PENDING, REPORT = "PASS", "FAIL", "PENDING", "REPORT-ONLY"


def _canonical_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        items = [_canonical_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    value_type = f"{type(value).__module__}.{type(value).__qualname__}"
    raise TypeError(f"unsupported protocol value {value_type}")


def _spine_fingerprint(spine) -> dict:
    """Interpreter-independent identity and normalized source for a spine callable."""
    closure = getattr(spine, "__closure__", None) or ()
    try:
        raw_source = textwrap.dedent(inspect.getsource(spine)).replace("\r\n", "\n")
    except (OSError, TypeError):
        raise ValueError(
            f"protocol spine source unavailable for {spine.__module__}.{spine.__qualname__}"
        ) from None
    source = "\n".join(line.rstrip() for line in raw_source.strip().splitlines()) + "\n"
    return {
        "identity": f"{spine.__module__}.{spine.__qualname__}",
        "source": source,
        "closure": [_canonical_value(cell.cell_contents) for cell in closure],
    }


def protocol_hash() -> str:
    """Deterministic hash over the frozen instrument config, challenges, panel, env, rubric,
    judge prompt. Any change flips the hash and forces re-certification (no quiet edits)."""
    challenges = []
    for challenge in load_challenges():
        encoded = {}
        for field in fields(challenge):
            value = getattr(challenge, field.name)
            if field.name == "spine":
                encoded["spine"] = _spine_fingerprint(value)
            else:
                encoded[field.name] = value
        challenges.append(encoded)
    payload = {
        "candidate_families": list(CANDIDATE_FAMILIES),
        "challenges": challenges,
        "environment_model": EXP0_ENV_MODEL,
        "judge_system": JUDGE_SYSTEM,
        "panel": [
            {
                "family": judge.family,
                "key": judge.key,
                "model": judge.model,
                "provider_key": judge.provider_key,
            }
            for judge in DEFAULT_PANEL
        ],
        "rubric_version": RUBRIC_VERSION,
        "thresholds": THRESHOLDS,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _load(name: str):
    p = layout.EXP0 / name
    return json.loads(p.read_text()) if p.exists() else None


# --- per-gate computations (each returns dict: value, status, detail) ---------------------

def _gate_floor() -> dict:
    f = _load("floor.json")
    if not f:
        return {"value": "", "status": PENDING, "detail": "floor not run (exp0 floor)"}
    passed = f.get("passed")
    return {"value": "pass" if passed else "FAIL", "status": PASS if passed else FAIL,
            "detail": f"env={f.get('env_model')} + {len(f.get('judges', []))} judges on "
                      f"{f.get('n_challenges', '?')} challenges"}


def _gate_provenance() -> dict:
    return {
        "value": "retrospective only",
        "status": FAIL,
        "detail": "reviewed source shards lack a collection-time protocol/rubric stamp; "
                  "a current code hash cannot retroactively certify them",
    }


def _solve_rates(verdicts: list[dict]) -> dict:
    by_ch: dict = {}
    for v in verdicts:
        by_ch.setdefault(v["challenge_id"], []).append(1 if v.get("solved") else 0)
    return {ch: sum(xs) / len(xs) for ch, xs in by_ch.items() if xs}


def _gate_ambiguity(verdicts) -> dict:
    if not verdicts:
        return {"value": "", "status": PENDING, "detail": "no panel verdicts yet"}
    t = THRESHOLDS["challenge_ambiguity"]
    rates = _solve_rates(verdicts)
    saturated = [f"{ch} {r*100:.0f}%" for ch, r in rates.items()
                 if r < t["min_solve"] or r > t["max_solve"]]
    lo, hi = (min(rates.values()), max(rates.values())) if rates else (0, 0)
    status = PASS if not saturated else FAIL
    return {"value": f"span {lo*100:.0f}–{hi*100:.0f}%", "status": status,
            "detail": ("no challenge saturates" if not saturated
                       else f"SATURATED: {', '.join(saturated)}")}


def _gate_panel(verdicts) -> dict:
    if not verdicts:
        return {"value": "", "status": PENDING, "detail": "no panel verdicts yet"}
    t = THRESHOLDS["panel_agreement"]
    # H1: drop cells with <2 valid judges (reached_pair_agreement is None), they have no
    # measurable agreement and would otherwise inflate the mean toward a false PASS.
    all_cells = [v["agreement"] for v in verdicts if "agreement" in v]
    agrees = [a["reached_pair_agreement"] for a in all_cells
              if a.get("reached_pair_agreement") is not None]
    dropped = len(all_cells) - len(agrees)
    if not agrees:
        return {"value": "", "status": PENDING,
                "detail": f"no scorable cells ({dropped} dropped for <2 valid judges)"}
    mean_agree = sum(agrees) / len(agrees)
    status = PASS if mean_agree >= t["min_reached_pair"] else FAIL
    # Diagnostic: when agreement fails, name the outlier. Over full-3-judge cells, compute each
    # judge's reached-rate (a near-1.0 rate = a non-discriminating rubber-stamp) and the pairwise
    # agreements (a tight frontier pair + one loose judge localises the problem to that judge).
    diag = _panel_diagnostics(verdicts)
    drop_note = (f"; {dropped} cell(s) <2 valid judges (gpt-5.1 rate-limit errors)"
                 if dropped else "")
    return {"value": f"{mean_agree:.2f}", "status": status,
            "detail": f"mean reached pair-agreement (thr ≥{t['min_reached_pair']}){drop_note}. "
                      f"{diag}"}


def _panel_diagnostics(verdicts: list[dict]) -> str:
    """Per-judge reached-rate + pairwise agreement over full-3-judge cells, localises a panel
    disagreement to the outlier judge (e.g. a judge that says 'reached' ~always isn't grading)."""
    full = [v for v in verdicts if v.get("agreement", {}).get("n_valid_judges") == 3]
    if not full:
        return "(no full-3-judge cells to diagnose)"
    keys = sorted({k for v in full for k in v["judges"]})
    rates = {}
    for k in keys:
        t = sum(1 for v in full if v["judges"][k]["reached"] is True)
        rates[k] = t / len(full)
    pairs = {}
    for i, x in enumerate(keys):
        for y in keys[i + 1:]:
            same = sum(1 for v in full
                       if v["judges"][x]["reached"] == v["judges"][y]["reached"])
            pairs[f"{x}|{y}"] = same / len(full)
    rate_str = " ".join(f"{k}={r*100:.0f}%" for k, r in rates.items())
    pair_str = " ".join(f"{p}={a:.2f}" for p, a in pairs.items())
    return f"n={len(full)} full cells · reached-rate[{rate_str}] · pair-agree[{pair_str}]"


def _gate_judge_reliability() -> dict:
    rs = _load("rescore.json")
    if not rs:
        return {"value": "", "status": PENDING, "detail": "test-retest not run (exp0 rescore)"}
    t = THRESHOLDS["judge_reliability"]
    rows = rs.get("rows", [])
    worst = None
    per_judge = {}
    for j in DEFAULT_PANEL:
        jr = [r for r in rows if r["judge"] == j.key]
        if not jr:
            continue
        rel = sum(r["agreement"]["reached_modal_frac"] for r in jr) / len(jr)
        per_judge[j.key] = rel
        worst = rel if worst is None else min(worst, rel)
    if worst is None:
        return {"value": "", "status": PENDING, "detail": "no rescore rows"}
    status = PASS if worst >= t["target"] else (REPORT if worst >= t["floor"] else FAIL)
    detail = " · ".join(f"{k} {v:.2f}" for k, v in per_judge.items())
    return {"value": f"min {worst:.2f}", "status": status,
            "detail": f"{detail} (floor {t['floor']}, target {t['target']})"}


def _gate_blind() -> dict:
    b = _load("blind.json")
    if not b:
        return {"value": "", "status": PENDING, "detail": "blinding not run (exp0 blind)"}
    chance = b.get("chance", 1 / len(CANDIDATE_FAMILIES))
    margin = THRESHOLDS["blind_leakage"]["max_over_chance"]
    rows = b.get("rows", [])
    worst_over = None
    per_judge = {}
    for j in DEFAULT_PANEL:
        graded = [r for r in rows if r["guesses"].get(j.key, {}).get("parse_ok")]
        if not graded:
            continue
        correct = sum(1 for r in graded if r["guesses"][j.key]["family"] == r["true_family"])
        acc = correct / len(graded)
        per_judge[j.key] = acc
        over = Fraction(correct, len(graded)) - Fraction(str(chance))
        worst_over = over if worst_over is None else max(worst_over, over)
    if worst_over is None:
        return {"value": "", "status": PENDING, "detail": "no graded guesses"}
    status = PASS if worst_over <= Fraction(str(margin)) else FAIL
    detail = " · ".join(f"{k} {v*100:.0f}%" for k, v in per_judge.items())
    worst_accuracy = float(worst_over + Fraction(str(chance)))
    return {"value": f"max {(worst_accuracy*100):.0f}% vs {chance*100:.0f}% chance",
            "status": status,
            "detail": f"{detail} (fail if >chance+{margin*100:.0f}pp)"}


def _gate_human(verdicts) -> dict:
    """Panel↔human agreement on the blinded calibration sample. Reads a COMPLETED scoring sheet
    (human-calibration/scoring-sheet-filled.csv); PENDING until a human returns it."""
    filled = layout.EXP0_HUMAN / "scoring-sheet-filled.csv"
    key = layout.EXP0_HUMAN / "answer-key.json"
    if not (filled.exists() and key.exists()):
        return {"value": "", "status": PENDING,
                "detail": "awaiting human labels (export-human → reviewer fills "
                          "scoring-sheet-filled.csv)"}
    answer = json.loads(key.read_text())
    t = THRESHOLDS["human_anchor"]
    lines = [ln.strip() for ln in filled.read_text().splitlines() if ln.strip()]
    hdr, *body = lines
    cols = hdr.split(",")
    pj_agree = jj_agree = n = tied = 0
    for row in body:
        cells = dict(zip(cols, row.split(",")))
        pid = cells.get("packet_id")
        hr = cells.get("reached(y/n)", "").strip().lower()
        if pid not in answer or hr not in ("y", "n"):
            continue
        human_reached = hr == "y"
        panel = answer[pid].get("panel", {})
        reached_votes = [jv.get("reached") for jv in panel.values()
                         if jv.get("reached") is not None]
        if not reached_votes:
            continue
        true_votes = sum(reached_votes)
        false_votes = len(reached_votes) - true_votes
        if true_votes == false_votes:
            tied += 1
            continue
        panel_reached = true_votes > false_votes
        pj_agree += int(panel_reached == human_reached)
        # judge↔judge unanimity on this item (for the side-by-side gap)
        jj_agree += int(len(set(reached_votes)) <= 1)
        n += 1
    if not n:
        tie_note = f"; {tied} tied cell(s) dropped" if tied else ""
        return {"value": "", "status": PENDING,
                "detail": f"scoring sheet has no usable strict-majority rows{tie_note}"}
    pj = pj_agree / n
    jj = jj_agree / n
    gap = jj - pj
    ok = pj >= t["min_agreement"] and gap <= t["max_gap_below_jj"]
    tie_note = f"; {tied} tied cell(s) dropped" if tied else ""
    return {"value": f"panel↔human {pj:.2f}", "status": PASS if ok else FAIL,
            "detail": f"vs judge↔judge {jj:.2f} (gap {gap:+.2f}; n={n}{tie_note}; "
                      f"thr ≥{t['min_agreement']}, gap ≤{t['max_gap_below_jj']})"}


def _gate_oracle_fn() -> dict:
    """Oracle false-negative rate vs the ground-truth anchor. Needs the execution/human-anchored
    gold labels; PENDING until that sample exists (prereg Tension 1). The synthetic-gold bound
    from `exp0 oracle` (canonical fix re-feed) is surfaced as a diagnostic but never sets the
    gate, canonical phrasing underestimates FN on real, differently-worded subject fixes."""
    g = _load("oracle-anchor.json")
    if not g:
        return {"value": "", "status": PENDING,
                "detail": "awaiting anchored gold labels, run `exp0 oracle`, then human labels "
                          "(export-human → scoring-sheet-filled.csv)"}
    t = THRESHOLDS["oracle_fn"]
    fn = g.get("fn_rate")
    if fn is None:
        syn = g.get("fn_rate_synthetic")
        syn_s = f"synthetic-gold diagnostic fn={syn*100:.0f}% (canonical phrasing); " \
            if syn is not None else ""
        return {"value": "", "status": PENDING,
                "detail": f"{syn_s}anchored fn_rate pending: human labels "
                          "(human-calibration/scoring-sheet-filled.csv), no execution "
                          "harness exists for EXECUTION_ANCHORED challenges"}
    return {"value": f"{fn*100:.0f}%", "status": PASS if fn <= t["max_fn"] else FAIL,
            "detail": f"false-negative vs anchor (thr ≤{t['max_fn']*100:.0f}%)"}


def _gate_oracle_consistency() -> dict:
    g = _load("oracle-anchor.json")
    if not g or g.get("consistency") is None:
        return {"value": "", "status": PENDING,
                "detail": "awaiting oracle re-feed (identical fix → identical verdict)"}
    t = THRESHOLDS["oracle_consistency"]
    cons = g["consistency"]
    return {"value": f"{cons:.2f}", "status": PASS if cons >= t["min"] else FAIL,
            "detail": f"identical-fix accept/reject stability (thr ≥{t['min']})"}


_GATES = [
    ("oracle false-negative rate", _gate_oracle_fn, "hard"),
    ("oracle consistency", _gate_oracle_consistency, "hard"),
    ("judge individual reliability", _gate_judge_reliability, "hard"),
    ("panel inter-judge agreement", _gate_panel, "hard"),
    ("human-anchor agreement", _gate_human, "hard"),
    ("blind leakage (provider-guess)", _gate_blind, "hard"),
    ("challenge ambiguity", _gate_ambiguity, "hard"),
    ("floor-gate", _gate_floor, "hard"),
    ("provenance", _gate_provenance, "hard"),
]


def compute_gates() -> list[dict]:
    verdicts = _load("verdicts.json") or []
    out = []
    for name, fn, kind in _GATES:
        # gates that read panel verdicts take them; others ignore the arg
        try:
            res = fn(verdicts) if fn in (_gate_ambiguity, _gate_panel, _gate_human) else fn()
        except Exception as e:  # noqa: BLE001, a broken gate reports, never crashes the report
            res = {"value": "ERR", "status": FAIL, "detail": f"{type(e).__name__}: {e}"}
        out.append({"gate": name, "kind": kind, **res})
    return out


# Core gates the env≠judge panel run itself produces. These MUST be measured-and-passing for
# any certification; if one is still pending the instrument simply hasn't been measured yet.
# The auxiliary gates (human anchor, oracle gold/consistency) legitimately lag behind the run
# they need a human reviewer and an execution/gold anchor, so pending-auxiliary downgrades to
# CONDITIONAL with a named caveat rather than blocking outright.
_CORE_GATES = {
    "floor-gate", "challenge ambiguity", "panel inter-judge agreement",
    "judge individual reliability", "blind leakage (provider-guess)", "provenance",
}


def verdict(gates: list[dict]) -> tuple[str, list[str]]:
    hard = [g for g in gates if g["kind"] == "hard"]
    failed = [g["gate"] for g in hard if g["status"] == FAIL]
    pending = [g["gate"] for g in hard if g["status"] == PENDING]
    report_only = [g["gate"] for g in hard if g["status"] == REPORT]
    if failed:
        caveats = [f"FAILED: {g}" for g in failed]
        caveats += [f"PENDING (auxiliary): {g}" for g in pending if g not in _CORE_GATES]
        return "NOT CERTIFIED", caveats
    core_pending = [g for g in pending if g in _CORE_GATES]
    if core_pending:
        return "NOT CERTIFIED", [f"NOT YET MEASURED (core): {g}" for g in core_pending] \
            + [f"PENDING (auxiliary): {g}" for g in pending if g not in _CORE_GATES]
    caveats = [f"PENDING (auxiliary): {g}" for g in pending]
    caveats += [f"below target (report-only): {g}" for g in report_only]
    if caveats:
        return "CONDITIONALLY CERTIFIED", caveats
    return "CERTIFIED", []


def generate_report(study_id: str = "exp0-instrument-validation", date: str = "") -> str:
    from model_familiarity.variance import decompose

    gates = compute_gates()
    vdt, caveats = verdict(gates)
    var = decompose()

    lbl = {
        "oracle false-negative rate": "oracle false-negative rate ..",
        "oracle consistency": "oracle consistency ...........",
        "judge individual reliability": "judge individual reliability .",
        "panel inter-judge agreement": "panel inter-judge agreement ..",
        "human-anchor agreement": "human-anchor agreement .......",
        "blind leakage (provider-guess)": "blind leakage (provider-guess)",
        "challenge ambiguity": "challenge ambiguity ..........",
        "floor-gate": "floor-gate ...................",
        "provenance": "provenance ...................",
    }
    out = [
        f"INSTRUMENT HEALTH, study {study_id}, protocol hash {protocol_hash()}"
        + (f"{date}" if date else ""),
        "",
    ]
    for g in gates:
        out.append(f"  {lbl[g['gate']]} {g['value']:<26} [{g['status']}]   {g['detail']}")
    out.append(f"  rubric / protocol hash ....... {RUBRIC_VERSION} / {protocol_hash()}")
    out.append("")
    if var and "subject_signal_to_noise" in var:
        snr = var["subject_signal_to_noise"]
        ci = var.get("snr_ci95", {})
        out.append(f"  [variance] subject signal-to-noise = {snr} "
                   f"(CI95 {ci.get('lo')}–{ci.get('hi')}); subject {var['subject_frac']} / "
                   f"judge {var['judge_frac']} / sampling {var['sample_frac']} of total var")
        out.append("")
    out.append(f"  VERDICT: {vdt}")
    for c in caveats:
        out.append(f"           - {c}")
    return "\n".join(out)


def main(date: str = ""):
    report = generate_report(date=date)
    layout.ensure()
    (layout.EXP0 / "health-report.md").write_text(report + "\n")
    # machine-readable gate table beside the human report (same computation, one source)
    gates = compute_gates()
    vdt, caveats = verdict(gates)
    (layout.EXP0 / "gates.json").write_text(json.dumps(
        {"protocol_hash": protocol_hash(), "rubric": RUBRIC_VERSION,
         "verdict": vdt, "caveats": caveats, "gates": gates}, indent=2))
    rows = ["| gate | value | status | detail |", "|---|---|---|---|"]
    rows += [f"| {g['gate']} | {g['value']} | {g['status']} | {g['detail']} |" for g in gates]
    rows += ["", f"**VERDICT: {vdt}**"] + [f"- {c}" for c in caveats]
    (layout.EXP0 / "gate-results.md").write_text(
        f"# Exp 0 gate results, protocol {protocol_hash()}\n\n" + "\n".join(rows) + "\n")
    print(report)
    print(f"\nwrote {layout.EXP0/'health-report.md'} + gates.json + gate-results.md")


if __name__ == "__main__":
    main()
