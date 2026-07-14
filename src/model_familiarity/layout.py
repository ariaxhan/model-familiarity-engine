"""Package-safe paths for bundled aggregate evaluation artifacts."""

from __future__ import annotations

from importlib.resources import files

EXP0 = files("model_familiarity").joinpath("data", "exp0")
EXP0_HUMAN = EXP0.joinpath("human-calibration")


def ensure() -> None:
    """Compatibility no-op: bundled public findings are immutable package data."""
