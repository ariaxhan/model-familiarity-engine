# Exp 0 gate results, protocol 9a730f21729df095

| gate | value | status | detail |
|---|---|---|---|
| oracle false-negative rate |  | PENDING | synthetic-gold diagnostic fn=0% (canonical phrasing); anchored fn_rate pending: human labels (human-calibration/scoring-sheet-filled.csv), no execution harness exists for EXECUTION_ANCHORED challenges |
| oracle consistency | 0.95 | PASS | identical-fix accept/reject stability (thr ≥0.9) |
| judge individual reliability | min 0.92 | PASS | judge_a 1.00 · judge_b 0.97 · judge_c 0.92 (floor 0.71, target 0.8) |
| panel inter-judge agreement | 0.74 | PASS | mean reached pair-agreement (thr ≥0.67). n=339 full cells · reached-rate[judge_a=76% judge_b=42% judge_c=50%] · pair-agree[judge_a|judge_b=0.65 judge_a|judge_c=0.73 judge_b|judge_c=0.84] |
| human-anchor agreement |  | PENDING | awaiting human labels (export-human → reviewer fills scoring-sheet-filled.csv) |
| blind leakage (provider-guess) | max 40% vs 25% chance | PASS | judge_a 17% · judge_b 40% · judge_c 37% (fail if >chance+15pp) |
| challenge ambiguity | span 25–87% | PASS | no challenge saturates |
| floor-gate | pass | PASS | env=qwen.qwen3-235b-a22b-2507-v1:0 + 3 judges on 8 challenges |
| provenance | retrospective only | FAIL | 5 source shard hashes verified for byte custody, but no collection-time protocol/rubric stamp exists |

**VERDICT: NOT CERTIFIED**
- FAILED: provenance
- PENDING (auxiliary): oracle false-negative rate
- PENDING (auxiliary): human-anchor agreement
