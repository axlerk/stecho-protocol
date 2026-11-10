# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""
Syndrome-Trellis Codes (STC) encoder / decoder.

Reference: T. Filler, J. Judas, J. Fridrich, "Minimizing Additive Distortion
in Steganography Using Syndrome-Trellis Codes", IEEE TIFS 6(3) 920–935, 2011.

Layer v2 uses one sub-matrix per rate rung with variable block widths
(`block_widths`, `stc_encode_v2`, `stc_decode_v2`; the matrices live in
stecho_v2.py). The fixed-rate matrix of the retired layer v1 (no shipping
build reads v1 since 2026-11-10) stays below only as the `STC_H_V1`
constraint height every v2 rung shares and as the baseline
`stc_submatrix_search.py` compares its candidates against:

    h = 10  (constraint height, 1024 trellis states)
    w = 12  (sub-matrix width, gives embedding rate 1/12 ≈ 0.0833 bpac)
    Ĥ      = [581, 831, 659, 877, 781, 929, 1003, 1021, 655, 729, 983, 611]

Pinned from the Binghamton STC reference implementation
(ml_stc_linux_make_v1.0, mats[] array at offset (10-7)*400 + (12-1)*20).
Each value is a 10-bit column read LSB-first: bit r of Ĥ column c equals
(SUBMATRIX[c] >> r) & 1.

For full theoretical background see the paper. The encoder is Viterbi
forward + backward traceback; the decoder is a single linear pass
H · x_stego (mod 2).
"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np


# -----------------------------------------------------------------------------
# Constraint height (shared by every v2 rung) and the retired v1 matrix
# -----------------------------------------------------------------------------

STC_H_V1 = 10
STC_W_V1 = 12
STC_SUBMATRIX_V1: Tuple[int, ...] = (
    581, 831, 659, 877, 781, 929, 1003, 1021, 655, 729, 983, 611,
)


# -----------------------------------------------------------------------------
# Layer v2: one sub-matrix per rung, block widths from a rational rate
# -----------------------------------------------------------------------------
#
# Layer v2 (juniward-layer.md §V2.5-§V2.6) embeds at a rate q/d bits per cover
# element. Syndrome bit j owns a block of
#
#     w(j) = floor((j + 1) * d / q) - floor(j * d / q)
#
# consecutive cover elements, so the widths take at most two values
# (floor(d/q) and ceil(d/q)) and m blocks span exactly floor(m * d / q)
# elements. A block of width w(j) uses the first w(j) columns of the rung's
# sub-matrix, which has ceil(d/q) columns. The parity-check matrix H is the
# usual staggered one truncated to m rows: column c of block j contributes
# bit r of the sub-matrix column to row j + r, for j + r < m.

def block_widths(m: int, q: int, d: int) -> np.ndarray:
    """Widths w(0..m-1) of the v2 block pattern for rate q/d."""
    if m < 0 or q < 1 or d < q:
        raise ValueError(f"bad block pattern m={m} q={q} d={d}")
    j = np.arange(m + 1, dtype=np.int64)
    edges = (j * d) // q
    return np.diff(edges)


def _block_layout(widths: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Per cover element: (block index j, column index inside the block)."""
    widths = np.asarray(widths, dtype=np.int64)
    m = widths.shape[0]
    block = np.repeat(np.arange(m, dtype=np.int64), widths)
    starts = np.concatenate(([0], np.cumsum(widths)[:-1])) if m else np.zeros(0, np.int64)
    col = np.arange(block.shape[0], dtype=np.int64) - starts[block]
    return block, col


def stc_decode_v2(
    stego_lsbs: np.ndarray,
    sub_matrix: Sequence[int],
    widths: np.ndarray,
    h: int = STC_H_V1,
) -> np.ndarray:
    """m = len(widths) message bits from n = sum(widths) stego LSBs: H · x mod 2
    with the truncated staggered H described above. Vectorised; normative
    semantics are the plain loop in juniward-layer.md §V2.8."""
    stego_lsbs = np.asarray(stego_lsbs, dtype=np.uint8)
    widths = np.asarray(widths, dtype=np.int64)
    m = widths.shape[0]
    n = int(widths.sum())
    if stego_lsbs.shape[0] != n:
        raise ValueError(f"stego length {stego_lsbs.shape[0]} != sum(widths) = {n}")
    if m and int(widths.max()) > len(sub_matrix):
        raise ValueError("a block is wider than the sub-matrix")
    cols = np.asarray(sub_matrix, dtype=np.int64)
    block, col = _block_layout(widths)
    ones = stego_lsbs == 1
    j = block[ones]
    mask = cols[col[ones]]
    message = np.zeros(m, dtype=np.int64)
    for r in range(h):
        rows = j[((mask >> r) & 1) == 1] + r
        rows = rows[rows < m]
        message ^= np.bincount(rows, minlength=m) & 1
    return message.astype(np.uint8)


def stc_encode_v2(
    cover_lsbs: np.ndarray,
    costs: np.ndarray,
    message: np.ndarray,
    sub_matrix: Sequence[int],
    widths: np.ndarray,
    h: int = STC_H_V1,
) -> np.ndarray:
    """Minimum-cost stego LSBs with H · stego = message (mod 2), H truncated
    to m rows (any final trellis state is accepted). Informative: any encoder
    whose output satisfies the syndrome equation is conforming."""
    cover_lsbs = np.asarray(cover_lsbs, dtype=np.uint8)
    costs = np.asarray(costs, dtype=np.float64)
    message = np.asarray(message, dtype=np.uint8)
    widths = np.asarray(widths, dtype=np.int64)
    m = widths.shape[0]
    n = int(widths.sum())
    if cover_lsbs.shape != (n,) or costs.shape != (n,):
        raise ValueError(f"cover/costs length must equal sum(widths) = {n}")
    if message.shape != (m,):
        raise ValueError(f"message length {message.shape[0]} != len(widths) = {m}")
    if m == 0:
        return cover_lsbs.copy()
    if int(widths.max()) > len(sub_matrix):
        raise ValueError("a block is wider than the sub-matrix")

    num_states = 1 << h
    half = num_states >> 1
    inf = np.float64(np.inf)
    state_idx = np.arange(num_states, dtype=np.int64)
    xor_table = np.stack([state_idx ^ int(c) for c in sub_matrix])
    block, col = _block_layout(widths)
    last_in_block = np.zeros(n, dtype=bool)
    last_in_block[np.cumsum(widths) - 1] = True

    path_cost = np.full(num_states, inf)
    path_cost[0] = 0.0
    # One bit per (step, state): "stego LSB at this step was 1" on the best
    # path into that state. Packed, n * 2^h / 8 bytes.
    choice = np.zeros((n, num_states // 8), dtype=np.uint8)
    upper = np.full(half, inf)

    for i in range(n):
        flip = float(costs[i])
        if cover_lsbs[i]:
            c0, c1 = path_cost + flip, path_cost[xor_table[col[i]]]
        else:
            c0, c1 = path_cost, path_cost[xor_table[col[i]]] + flip
        take1 = c1 < c0
        new_cost = np.where(take1, c1, c0)
        choice[i] = np.packbits(take1)
        if last_in_block[i]:
            # Row j is complete: keep states whose row-j bit equals the
            # message bit, then shift row j out.
            bit = int(message[block[i]])
            path_cost = np.concatenate((new_cost[bit::2], upper))
        else:
            path_cost = new_cost

    state = int(np.argmin(path_cost))
    if not np.isfinite(path_cost[state]):
        raise ValueError("STC encoding failed: no valid path")
    stego = np.zeros(n, dtype=np.uint8)
    for i in range(n - 1, -1, -1):
        if last_in_block[i]:
            state = (state << 1) | int(message[block[i]])
        s = (int(choice[i, state >> 3]) >> (7 - (state & 7))) & 1
        stego[i] = s
        if s:
            state ^= int(sub_matrix[col[i]])
    if state != 0:
        raise ValueError(f"STC traceback ended in state {state}, not 0 (bug)")
    return stego


# -----------------------------------------------------------------------------
# Self-test
# -----------------------------------------------------------------------------

def _self_test() -> None:
    """Verify encode+decode round-trip on small synthetic data."""
    rng = np.random.default_rng(42)
    h = STC_H_V1
    w = STC_W_V1
    submatrix = STC_SUBMATRIX_V1

    for trial in range(5):
        m = 64 + trial * 32                  # message length (varies)
        widths = block_widths(m, 1, w)       # rate 1/12: every block w = 12 wide
        n = int(widths.sum())                # cover length

        cover = rng.integers(0, 2, n, dtype=np.uint8)
        costs = rng.random(n, dtype=np.float64) + 0.1
        message = rng.integers(0, 2, m, dtype=np.uint8)

        stego = stc_encode_v2(cover, costs, message, submatrix, widths, h)
        recovered = stc_decode_v2(stego, submatrix, widths, h)

        n_changes = int(np.sum(cover != stego))
        total_cost = float(np.sum(costs[cover != stego]))

        if not np.array_equal(recovered, message):
            raise AssertionError(
                f"trial {trial}: decoder recovered != original message"
            )
        print(
            f"  trial {trial}: n={n} m={m} → "
            f"{n_changes} flips, total cost = {total_cost:.3f} ✓"
        )

    print("STC self-test passed.")


if __name__ == "__main__":
    _self_test()
