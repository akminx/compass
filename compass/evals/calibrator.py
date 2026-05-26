"""Isotonic-regression score calibrator.

Once hand-labels exist, fit a monotonic mapping `predicted_score → true_score`
on a labeled subset and apply it to all subsequent predictions. Direct MAE +
bias reduction without changing the LLM.

Implementation is dependency-free: Pool Adjacent Violators (PAV) in ~30 lines.
sklearn.isotonic.IsotonicRegression would do the same job but adds a heavy dep
for a function this small. PAV is exact for the L2 isotonic problem and runs
in O(n log n) including the sort.

Workflow:
    >>> from compass.evals.calibrator import fit_isotonic, apply, save, load
    >>> pairs = [(scorer_score, true_score), ...]  # hand-labels
    >>> calibrator = fit_isotonic(pairs)
    >>> save(calibrator, "compass/evals/calibrator.json")
    >>> # at score time:
    >>> calibrated_score = apply(calibrator, raw_score)

Why this works: the eval surfaced a residual bias of ≈ −0.32 and a U-shaped
error pattern (out-of-scope JDs over-scored, strong-match JDs under-scored).
A monotonic remap can correct both: if the scorer's 2.5 is consistently the
judge's 1.5 on the low end and its 3.0 is consistently 4.5 on the high end,
isotonic regression learns that piecewise-constant correction with no risk of
inverting any rank order. The Spearman ρ is invariant under monotonic
transformation — calibration cannot make ranking worse, only better.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CALIBRATOR_PATH = Path(__file__).parent / "calibrator.json"


@dataclass(frozen=True)
class IsotonicCalibrator:
    """Piecewise-constant monotonic mapping built by Pool Adjacent Violators.

    `xs` are sorted predicted scores; `ys` are the corresponding pooled
    target values. To apply at score time we find the right bucket and
    return ys[i], with linear interpolation between adjacent xs to avoid
    step-function discontinuities.
    """

    xs: tuple[float, ...]
    ys: tuple[float, ...]
    n_training_pairs: int
    fit_mae: float  # post-fit MAE on training data (informational)


def fit_isotonic(pairs: list[tuple[float, float]]) -> IsotonicCalibrator:
    """Fit an isotonic regression via Pool Adjacent Violators.

    `pairs`: list of (predicted_score, true_score). Need >= 3 distinct
    predicted values to produce a non-trivial fit; below that, the
    calibrator degenerates to a constant or a single line and the harness
    should warn the user that the fit is over-parameterized.
    """
    if not pairs:
        raise ValueError("fit_isotonic: no pairs provided")
    if len(pairs) < 5:
        logger.warning(
            "fit_isotonic: only %d pairs — fit will be unreliable. Aim for >= 30 hand-labels.",
            len(pairs),
        )

    # Sort by x (predicted). Ties: average y values to avoid PAV instability.
    by_x: dict[float, list[float]] = {}
    for x, y in pairs:
        by_x.setdefault(float(x), []).append(float(y))
    sorted_x = sorted(by_x.keys())
    averaged: list[tuple[float, float, int]] = [
        (x, sum(by_x[x]) / len(by_x[x]), len(by_x[x])) for x in sorted_x
    ]

    # PAV: walk left→right, pool any adjacent block where the running mean
    # is non-monotonic, repeat until monotonic.
    blocks: list[list[float]] = []  # each block = [sum_y, weight, x_start, x_end]
    for x, y, w in averaged:
        blocks.append([y * w, w, x, x])
        while len(blocks) >= 2:
            mean_last = blocks[-1][0] / blocks[-1][1]
            mean_prev = blocks[-2][0] / blocks[-2][1]
            if mean_prev <= mean_last:
                break
            # Merge: sum, weight, span the x range.
            merged = [
                blocks[-2][0] + blocks[-1][0],
                blocks[-2][1] + blocks[-1][1],
                blocks[-2][2],
                blocks[-1][3],
            ]
            blocks.pop()
            blocks.pop()
            blocks.append(merged)

    # Materialize the piecewise function: one (x, y) per block start.
    xs: list[float] = []
    ys: list[float] = []
    for sum_y, w, x_start, _x_end in blocks:
        xs.append(x_start)
        ys.append(sum_y / w)

    cal = IsotonicCalibrator(
        xs=tuple(xs),
        ys=tuple(ys),
        n_training_pairs=len(pairs),
        fit_mae=0.0,  # filled in below
    )
    # MAE on training data — post-fit, informational only.
    train_mae = sum(abs(_interpolate(cal, p) - t) for p, t in pairs) / len(pairs)
    return IsotonicCalibrator(
        xs=cal.xs,
        ys=cal.ys,
        n_training_pairs=cal.n_training_pairs,
        fit_mae=round(train_mae, 4),
    )


def _interpolate(cal: IsotonicCalibrator, x: float) -> float:
    """Apply the piecewise mapping with linear interpolation between knots.

    Below xs[0]:  return ys[0]  (constant extrapolation — never extrapolate
                                 outside the training range; scoring scale is
                                 bounded [0, 5] anyway).
    Above xs[-1]: return ys[-1].
    Between:      linearly interpolate the two surrounding (x, y) knots.
    """
    if not cal.xs:
        return x  # degenerate calibrator: identity
    if x <= cal.xs[0]:
        return cal.ys[0]
    if x >= cal.xs[-1]:
        return cal.ys[-1]
    for i in range(1, len(cal.xs)):
        if x <= cal.xs[i]:
            x0, x1 = cal.xs[i - 1], cal.xs[i]
            y0, y1 = cal.ys[i - 1], cal.ys[i]
            if x1 == x0:  # shouldn't happen post-dedup, but guard
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return cal.ys[-1]  # unreachable


def apply(cal: IsotonicCalibrator | None, score: float) -> float:
    """Apply a calibrator to a raw score. None → identity (calibrator
    not yet fit). Output is clamped to [0, 5] to match JobScore.score's
    constraint."""
    if cal is None:
        return score
    return max(0.0, min(5.0, _interpolate(cal, score)))


def save(cal: IsotonicCalibrator, path: Path | None = None) -> Path:
    p = path or CALIBRATOR_PATH
    p.write_text(
        json.dumps(
            {
                "xs": list(cal.xs),
                "ys": list(cal.ys),
                "n_training_pairs": cal.n_training_pairs,
                "fit_mae": cal.fit_mae,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return p


def load(path: Path | None = None) -> IsotonicCalibrator | None:
    """Load a previously-saved calibrator. Returns None when no calibrator
    file exists (cold-start case — fit one first via `fit_from_labels`).
    """
    p = path or CALIBRATOR_PATH
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    return IsotonicCalibrator(
        xs=tuple(raw["xs"]),
        ys=tuple(raw["ys"]),
        n_training_pairs=raw["n_training_pairs"],
        fit_mae=raw.get("fit_mae", 0.0),
    )


def fit_from_labels(path: Path | None = None) -> IsotonicCalibrator:
    """Convenience: load the labeled dataset, run the production scorer on
    each record at ensemble_n=3, fit the calibrator, save it.

    The runtime cost is one full eval pass. The benefit is a free MAE drop
    that's bounded only by the LLM-judge / ground-truth disagreement floor.
    Run after every meaningful change to the scorer (prompt, model, RAG).
    """
    import asyncio

    from compass.evals.dataset import load_dataset
    from compass.evals.runner import _run_extract_and_score

    records = load_dataset()
    labeled = [r for r in records if (r.expected_score or 0) > 0 or r.expected_skills]
    if len(labeled) < 5:
        raise SystemExit(
            f"fit_from_labels: only {len(labeled)} hand-labeled records found. "
            "Label at least 5 (ideally 30+) via `uv run python -m scripts.label_jd <file>`."
        )

    async def _collect() -> list[tuple[float, float]]:
        pairs: list[tuple[float, float]] = []
        for r in labeled:
            _req, score, _elapsed, _rf = await _run_extract_and_score(r, ensemble_n=3)
            if score is None:
                continue
            pairs.append((score.score, r.expected_score))
        return pairs

    pairs = asyncio.run(_collect())
    cal = fit_isotonic(pairs)
    save_path = save(cal, path)
    logger.info(
        "calibrator fit: n=%d pairs, train_mae=%.3f, knots=%d, written to %s",
        cal.n_training_pairs, cal.fit_mae, len(cal.xs), save_path,
    )
    return cal


def _cli() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Isotonic calibrator CLI.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fit", help="Re-fit the calibrator from the labeled dataset.")
    info = sub.add_parser("info", help="Print the current calibrator's knots.")
    info.set_defaults(cmd="info")
    args = parser.parse_args()

    if args.cmd == "fit":
        cal = fit_from_labels()
        print(
            f"fit: n={cal.n_training_pairs} pairs, train_mae={cal.fit_mae}, "
            f"knots={len(cal.xs)}, file={CALIBRATOR_PATH}"
        )
        return 0
    if args.cmd == "info":
        cal = load()
        if cal is None:
            print("no calibrator on disk — run `python -m compass.evals.calibrator fit` first.")
            return 1
        print(f"n_training_pairs: {cal.n_training_pairs}")
        print(f"train_mae:        {cal.fit_mae}")
        print(f"knots ({len(cal.xs)}):")
        for x, y in zip(cal.xs, cal.ys, strict=True):
            print(f"  x={x:.2f} → y={y:.2f}")
        return 0
    print(f"unknown command: {args.cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
