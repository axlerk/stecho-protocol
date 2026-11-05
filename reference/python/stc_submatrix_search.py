#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""Seeded search for the layer-v2 STC sub-matrices (juniward-layer.md §V2.6.3).

The Binghamton STC table that layer v1 took its w = 12 sub-matrix from
covers widths up to 20 only, and v2 needs widths 40, 20, 10, 5 and 3 at
h = 10. This script derives one sub-matrix per rung the way Filler, Judas and
Fridrich describe theirs being found: draw random candidates, keep the one
with the lowest distortion on simulated covers. Everything is seeded, so a
re-run prints the same table.

Candidates: ceil(d/q) distinct 10-bit columns with bit 0 and bit 9 set (the
first and last rows of the sub-matrix all ones, as in every column of the v1
matrix). Score: mean total distortion of `stc_encode_v2` over trials with
i.i.d. uniform costs on (0, 1], random cover LSBs and random messages, with
the rung's own block pattern, divided by the distortion bound of the optimal
embedding simulator for the same costs and payload. Stage 1 scores every
candidate on a few trials, stage 2 re-scores the best ones on more trials;
all candidates share the same trial data (paired comparison).

The `--validate` mode runs the same scoring at w = 12 against the v1 matrix,
as a check that the scoring ranks a published matrix where one would expect.

Usage:
    python stc_submatrix_search.py [--n 10240] [--out result.json]
    python stc_submatrix_search.py --validate
"""

import argparse
import json
import math
import sys
import time

import numpy as np

from stc import STC_H_V1, STC_SUBMATRIX_V1, block_widths, stc_encode_v2

H = STC_H_V1
SEED = 20261104
# (rung, q, d): must match RUNGS_V2 in stecho_v2.py.
RUNGS = ((1, 1, 40), (2, 1, 20), (3, 1, 10), (4, 1, 5), (5, 2, 5))


def candidate(rng, width):
    cols = set()
    while len(cols) < width:
        cols.add(1 | (1 << (H - 1)) | (int(rng.integers(0, 1 << (H - 2))) << 1))
    return [int(c) for c in rng.permutation(sorted(cols))]


def trials(rng, count, n, q, d):
    m = (n * q) // d
    widths = block_widths(m, q, d)
    n_use = int(widths.sum())
    out = []
    for _ in range(count):
        costs = 1.0 - rng.random(n_use)            # (0, 1]
        cover = rng.integers(0, 2, n_use).astype(np.uint8)
        msg = rng.integers(0, 2, m).astype(np.uint8)
        out.append((cover, costs, msg, widths, bound(costs, m)))
    return out


def bound(costs, m):
    """Expected distortion of the optimal binary embedding simulator
    (p = 1 / (1 + e^{λρ}), Σ H2(p) = m), the rate-distortion bound."""
    def stats(lam):
        z = np.minimum(lam * costs, 700.0)
        p = 1.0 / (1.0 + np.exp(z))
        with np.errstate(divide="ignore", invalid="ignore"):
            h2 = -(p * np.log2(p) + (1 - p) * np.log2(1 - p))
        return np.nansum(h2), float(np.sum(p * costs))
    lo, hi = 1e-6, 1e4
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if stats(mid)[0] > m:
            lo = mid
        else:
            hi = mid
    return stats(hi)[1]


def score(cols, data):
    ratios = []
    for cover, costs, msg, widths, bnd in data:
        stego = stc_encode_v2(cover, costs, msg, cols, widths, H)
        ratios.append(float(costs[stego != cover].sum()) / bnd)
    return float(np.mean(ratios)), ratios


def search_rung(rung, q, d, n, k1, t1, k2, t2, log):
    width = -(-d // q)
    rng = np.random.default_rng([SEED, rung])
    cands = [candidate(rng, width) for _ in range(k1)]
    data1 = trials(rng, t1, n, q, d)
    data2 = trials(rng, t2, n, q, d)
    stage1 = sorted(((score(c, data1)[0], i) for i, c in enumerate(cands)))
    log(f"rung {rung} (rate {q}/{d}, width {width}): stage 1 best {stage1[0][0]:.4f}, "
        f"median {stage1[len(stage1) // 2][0]:.4f}, worst {stage1[-1][0]:.4f}")
    finals = []
    for s1, i in stage1[:k2]:
        s2, r2 = score(cands[i], data2)
        finals.append((s2, i, s1, r2))
    finals.sort()
    best = finals[0]
    log(f"rung {rung}: stage 2 best {best[0]:.4f} (candidate {best[1]}), "
        f"runner-up {finals[1][0]:.4f}")
    return {
        "rung": rung, "q": q, "d": d, "width": width,
        "columns": cands[best[1]],
        "candidate_index": best[1],
        "distortion_over_bound": round(best[0], 4),
        "stage2_trials": [round(x, 4) for x in best[3]],
        "stage1_best_median_worst": [round(stage1[0][0], 4),
                                     round(stage1[len(stage1) // 2][0], 4),
                                     round(stage1[-1][0], 4)],
    }


def validate(n, k, t, log):
    rng = np.random.default_rng([SEED, 12])
    data = trials(rng, t, n, 1, 12)
    v1, _ = score(list(STC_SUBMATRIX_V1), data)
    rand = sorted(score(candidate(rng, 12), data)[0] for _ in range(k))
    rank = sum(1 for r in rand if r < v1)
    log(f"w=12: v1 matrix {v1:.4f}; {k} random candidates best {rand[0]:.4f}, "
        f"median {rand[len(rand) // 2]:.4f}, worst {rand[-1]:.4f}; "
        f"{rank} of {k} random candidates beat the v1 matrix")
    return {"v1": round(v1, 4), "random": [round(r, 4) for r in rand], "beaten_by": rank}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10240, help="cover elements per trial")
    ap.add_argument("--k1", type=int, default=48)
    ap.add_argument("--t1", type=int, default=3)
    ap.add_argument("--k2", type=int, default=6)
    ap.add_argument("--t2", type=int, default=12)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--rungs", default="1,2,3,4,5")
    ap.add_argument("--out")
    a = ap.parse_args()

    def log(msg):
        print(msg, file=sys.stderr, flush=True)

    t0 = time.time()
    result = {"seed": SEED, "h": H, "n": a.n, "k1": a.k1, "t1": a.t1, "k2": a.k2, "t2": a.t2}
    if a.validate:
        result["validate"] = validate(a.n, 16, a.t2, log)
    else:
        want = {int(x) for x in a.rungs.split(",")}
        result["rungs"] = [search_rung(r, q, d, a.n, a.k1, a.t1, a.k2, a.t2, log)
                           for r, q, d in RUNGS if r in want]
    result["seconds"] = round(time.time() - t0, 1)
    text = json.dumps(result, indent=2)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
