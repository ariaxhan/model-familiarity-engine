"""Variance decomposition — is the subject signal bigger than the instrument's own noise?

The headline question of Exp 0 (prereg H0-variance): when an `lhcr_score` differs between two
cells, is that the *subject* differing, or the *instrument* (judge + sampling) being noisy? If
instrument variance dominates, no behavioural claim survives at the current k — you're reading
noise. The pilot couldn't answer this: k=2 with one judge entangled judge noise, sampling
noise, and subject signal into a single 71% number.

This partitions `lhcr_score` variance into three nested components, computed from the high-k
mini-study (few cells, large k, full 3-judge panel — prereg Tension 2):

  σ²_judge   — within ONE conversation, across the 3 judges (the transcript is fixed, so this
               is pure judge disagreement).
  σ²_sample  — within (subject, challenge, judge), across the k samples (the judge is fixed, so
               this is the subject + env re-sampling the conversation differently).
  σ²_subject — between subjects (each subject's mean score) — the signal we want to be able to read.

Reported as fractions of the total, plus the load-bearing ratio
``subject_signal_to_noise = σ²_subject / (σ²_judge + σ²_sample)`` with a bootstrap CI over
cells. > 1 means subject signal exceeds instrument noise (claimable); < 1 means raise k or fix
the noisy component first.
"""

from __future__ import annotations

import json
from statistics import mean, pvariance

from model_familiarity import layout


def _rows(verdicts: list[dict]) -> list[dict]:
    """Flatten panel verdicts into (subject, challenge, sample, judge, lhcr, reached) rows."""
    out = []
    for v in verdicts:
        for jkey, jv in v.get("judges", {}).items():
            out.append({
                "subject": v["model"], "challenge": v["challenge_id"],
                "sample": v.get("sample", 0), "judge": jkey,
                "lhcr": jv.get("lhcr_score", 0), "reached": jv.get("reached"),
                "solved": v.get("solved"),
            })
    return out


def _components(rows: list[dict]) -> dict:
    """Variance components of lhcr over the given rows.

    Four factors, not three (M1): the CHALLENGE main effect (easy vs hard) is usually the
    largest variance source in a benchmark, so it is estimated explicitly instead of being
    folded silently into the total — otherwise `total` is incomplete and every fraction is
    against a wrong denominator. Challenge is a fixed DESIGN factor, so it is reported but kept
    OUT of the instrument-noise denominator (it is neither instrument error nor subject signal).

    σ²_subject is corrected for sampling noise (M2): the raw variance of per-subject means
    overestimates the true between-subject component by ≈ σ²_within/m, which inflates the
    signal-to-noise ratio toward 'claimable'. We subtract that within term (floored at 0)."""
    if not rows:
        return {}

    # σ²_judge: across judges within each conversation (transcript fixed → pure judge disagreement)
    by_conv: dict = {}
    for r in rows:
        by_conv.setdefault((r["subject"], r["challenge"], r["sample"]), []).append(r["lhcr"])
    judge_var = mean([pvariance(v) for v in by_conv.values() if len(v) > 1]) \
        if any(len(v) > 1 for v in by_conv.values()) else 0.0

    # σ²_sample: across samples within each (subject,challenge,judge) → subject+env re-sampling
    by_cell: dict = {}
    for r in rows:
        by_cell.setdefault((r["subject"], r["challenge"], r["judge"]), []).append(r["lhcr"])
    cell_vars = [pvariance(v) for v in by_cell.values() if len(v) > 1]
    sample_var = mean(cell_vars) if cell_vars else 0.0

    # σ²_challenge: between-challenge means (the design's difficulty spread)
    by_ch: dict = {}
    for r in rows:
        by_ch.setdefault(r["challenge"], []).append(r["lhcr"])
    challenge_var = pvariance([mean(v) for v in by_ch.values()]) if len(by_ch) > 1 else 0.0

    # σ²_subject, corrected for within-subject sampling noise (M2)
    by_subj: dict = {}
    for r in rows:
        by_subj.setdefault(r["subject"], []).append(r["lhcr"])
    subj_means = [mean(v) for v in by_subj.values()]
    raw_subject_var = pvariance(subj_means) if len(subj_means) > 1 else 0.0
    within_subj = mean([pvariance(v) for v in by_subj.values() if len(v) > 1]) \
        if any(len(v) > 1 for v in by_subj.values()) else 0.0
    m = mean([len(v) for v in by_subj.values()]) if by_subj else 1
    subject_var = max(0.0, raw_subject_var - (within_subj / m if m else 0.0))

    total = judge_var + sample_var + subject_var + challenge_var
    instrument = judge_var + sample_var  # challenge is design, not instrument noise
    return {
        "judge_var": round(judge_var, 4),
        "sample_var": round(sample_var, 4),
        "challenge_var": round(challenge_var, 4),
        "subject_var": round(subject_var, 4),
        "subject_var_raw": round(raw_subject_var, 4),   # pre-correction, for transparency
        "total": round(total, 4),
        "judge_frac": round(judge_var / total, 4) if total else 0.0,
        "sample_frac": round(sample_var / total, 4) if total else 0.0,
        "challenge_frac": round(challenge_var / total, 4) if total else 0.0,
        "subject_frac": round(subject_var / total, 4) if total else 0.0,
        "subject_signal_to_noise": round(subject_var / instrument, 4) if instrument else None,
        "n_subjects": len(by_subj), "n_conversations": len(by_conv), "n_rows": len(rows),
    }


def _bootstrap_snr(rows: list[dict], iters: int = 500) -> dict:
    """Bootstrap CI for subject_signal_to_noise by resampling conversations with replacement.

    H3: uses a deterministically-SEEDED `random.Random` (not the global RNG, not an ad-hoc LCG)
    — fully reproducible run-to-run, but a real iid sampler. The earlier hand-rolled LCG
    indexed off `seed % n`, which for a power-of-2 modulus degenerates into a fixed permutation
    when n is a power of two (the mini-study's n = subjects×challenges×k is), collapsing the CI
    to a zero-width point. A proper PRNG resamples genuinely."""
    import random

    convs: dict = {}
    for r in rows:
        convs.setdefault((r["subject"], r["challenge"], r["sample"]), []).append(r)
    keys = list(convs.keys())
    n = len(keys)
    if n < 2:
        return {"lo": None, "hi": None, "iters": 0}
    rng = random.Random(20260628)  # fixed seed → reproducible CI; not the global RNG
    snrs = []
    for _ in range(iters):
        sampled_rows = []
        for _ in range(n):
            sampled_rows.extend(convs[keys[rng.randrange(n)]])
        snr = _components(sampled_rows).get("subject_signal_to_noise")
        if snr is not None:
            snrs.append(snr)
    if not snrs:
        return {"lo": None, "hi": None, "iters": 0}
    snrs.sort()
    lo = snrs[int(0.025 * len(snrs))]
    hi = snrs[min(len(snrs) - 1, int(0.975 * len(snrs)))]
    return {"lo": round(lo, 4), "hi": round(hi, 4), "iters": len(snrs)}


def decompose(variance_name: str = "variance.json") -> dict:
    """Variance decomposition over the high-k mini-study verdicts. Returns the component dict
    + bootstrap CI on subject signal-to-noise."""
    vpath = layout.EXP0 / variance_name
    if not vpath.exists():
        return {"error": f"no {variance_name} — run `exp0 variance` first"}
    verdicts = json.loads(vpath.read_text())
    rows = _rows(verdicts)
    comp = _components(rows)
    comp["snr_ci95"] = _bootstrap_snr(rows)
    return comp


def main():
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "variance.json"
    print(json.dumps(decompose(name), indent=2))


if __name__ == "__main__":
    main()
