"""Judge floor test — prove the measuring stick before trusting any verdict.

The commission requires every judge to pass a dummy-answer floor. We go further and
test the specific failure mode the whole project guards against — the similarity trap —
with three probe types per task:

- ``dummy``        : garbage / confidently-wrong answer. MUST score reached=False.
                     (A judge that passes garbage measures nothing.)
- ``correct_diff`` : a correct answer phrased very differently from Claude's. MUST score
                     reached=True. (A judge that fails this is a clone detector — it is
                     rewarding resemblance, not correctness. This is the trap probe.)

Floor PASSES only if every dummy is not-reached AND every correct_diff is reached. A
failure here is a failed build (commission → canon/failures/), not a number to massage.
"""

from __future__ import annotations

from dataclasses import dataclass

from model_familiarity.judge import DEFAULT_JUDGE_MODEL, judge
from model_familiarity.providers.base import BaseProvider
from model_familiarity.tasks import get_task

# (task_id, kind, answer_text). kind ∈ {"dummy", "correct_diff"}.
# correct_diff answers are deliberately un-Claude-like in voice/structure but reach the
# objective outcome. dummy answers are wrong — including ones that confidently BUY the
# false premise (the hardest case for the einstein task).
PROBES: list[tuple[str, str, str]] = [
    # --- empty-answer probe: a blank answer MUST score not-reached. Guards the leak
    #     where the judge rubber-stamps the known outcome onto nothing (found live with
    #     a reasoning model that emitted only reasoning, no answer). ---
    ("ios_zoom", "dummy", ""),
    ("annual_price", "dummy", "   \n  "),
    # --- ios_zoom (dummy = plausible-but-wrong diagnosis) ---
    (
        "ios_zoom",
        "dummy",
        "This is a flexbox issue — the input sits in a flex container that resizes on "
        "focus. Add flex-shrink: 0 to .desk-input and it'll stop moving.",
    ),
    (
        "ios_zoom",
        "correct_diff",
        "Classic iOS thing: any input with a font under 16px makes Safari/WKWebView zoom "
        "in on focus. Bump .desk-input to 16px and it stops. Don't set user-scalable=no "
        "to 'fix' it — that wrecks pinch-zoom accessibility.",
    ),
    # --- cover_crop ---
    (
        "cover_crop",
        "dummy",
        "The source image is probably exported at the wrong size. Try removing object-fit "
        "and setting height: auto so it isn't constrained.",
    ),
    (
        "cover_crop",
        "correct_diff",
        "Your card box is 3:4 but the strip image is 9:16 — way taller. object-fit: cover "
        "scales it to fill the box and chops the overflow off the top and bottom. Make the "
        "card 9:16 to match.",
    ),
    # --- annual_price ---
    (
        "annual_price",
        "dummy",
        "It's a currency formatting bug — wrap the formatted price in Intl.NumberFormat with the "
        "right locale and the price will render correctly.",
    ),
    (
        "annual_price",
        "correct_diff",
        "The yearly package has a full $79.99/yr price, not a monthly number, so "
        "putting it in pricePerMonth prints '$79.99/mo'. Divide the annual price by 12 "
        "instead.",
    ),
]


@dataclass
class ProbeResult:
    task_id: str
    kind: str
    reached: bool | None
    divergence: str
    agrees_with_spine: bool
    passed: bool
    how: str


async def run_floor(
    provider: BaseProvider, judge_model: str = DEFAULT_JUDGE_MODEL
) -> tuple[bool, list[ProbeResult]]:
    """Run every probe through the judge. Returns (overall_pass, results)."""
    results: list[ProbeResult] = []
    for task_id, kind, answer in PROBES:
        task = get_task(task_id)
        v = await judge(task, answer, provider, judge_model=judge_model)
        if kind == "dummy":
            passed = v.reached is False
        else:  # correct_diff
            passed = v.reached is True
        results.append(
            ProbeResult(
                task_id=task_id,
                kind=kind,
                reached=v.reached,
                divergence=v.divergence,
                agrees_with_spine=v.agrees_with_spine,
                passed=passed,
                how=v.how,
            )
        )
    overall = all(r.passed for r in results)
    return overall, results
