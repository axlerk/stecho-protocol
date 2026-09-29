# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""
Syndrome-Trellis Codes (STC) encoder / decoder.

Reference: T. Filler, J. Judas, J. Fridrich, "Minimizing Additive Distortion
in Steganography Using Syndrome-Trellis Codes", IEEE TIFS 6(3) 920–935, 2011.

This module implements the single-sub-matrix STC variant used by Stecho v1:

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
# v1 frozen parameters
# -----------------------------------------------------------------------------

STC_H_V1 = 10
STC_W_V1 = 12
STC_SUBMATRIX_V1: Tuple[int, ...] = (
    581, 831, 659, 877, 781, 929, 1003, 1021, 655, 729, 983, 611,
)
NUM_STATES_V1 = 1 << STC_H_V1   # 1024


# -----------------------------------------------------------------------------
# Encoder
# -----------------------------------------------------------------------------

def stc_encode(
    cover_lsbs: np.ndarray,
    costs: np.ndarray,
    message: np.ndarray,
    sub_matrix: Sequence[int] = STC_SUBMATRIX_V1,
    h: int = STC_H_V1,
) -> np.ndarray:
    """Returns the stego LSB vector minimizing sum of distortion `costs[i]`
    over flipped positions, subject to `H · stego = message` mod 2.

    Args:
        cover_lsbs: shape (n,) uint8 in {0, 1}. The LSBs of the cover.
        costs:      shape (n,) float64. Cost of flipping each cover LSB.
        message:    shape (m,) uint8 in {0, 1}. The syndrome / message bits.
        sub_matrix: list of w column values (each h-bit integer).
        h:          constraint height of the sub-matrix.

    Returns:
        stego_lsbs: shape (n,) uint8 in {0, 1}.

    Raises:
        ValueError if shapes or parameters are inconsistent.
    """
    cover_lsbs = np.asarray(cover_lsbs, dtype=np.uint8)
    costs = np.asarray(costs, dtype=np.float64)
    message = np.asarray(message, dtype=np.uint8)
    w = len(sub_matrix)
    n = cover_lsbs.shape[0]
    m = message.shape[0]

    if costs.shape != (n,):
        raise ValueError(f"costs shape {costs.shape} != cover shape ({n},)")
    if n != w * m:
        raise ValueError(
            f"cover length {n} must equal w*m = {w}*{m} = {w*m} "
            f"(modes must pad cover/message to satisfy this)"
        )

    num_states = 1 << h
    INF = np.float64(np.inf)

    # path_cost[s] = min cumulative cost to reach trellis state s right now.
    # path_choice[i, s] = stego LSB chosen at step i to land at state s.
    path_cost = np.full(num_states, INF, dtype=np.float64)
    path_cost[0] = 0.0
    path_choice = np.zeros((n, num_states), dtype=np.uint8)

    # Pre-build per-column XOR permutations once.
    state_idx = np.arange(num_states, dtype=np.int64)
    xor_table = np.empty((w, num_states), dtype=np.int64)
    for col_idx in range(w):
        xor_table[col_idx] = state_idx ^ int(sub_matrix[col_idx])

    # Vectorised Viterbi forward pass.
    #
    # State evolution at step i, parameterised by stego LSB s ∈ {0, 1}:
    #     new_state = old_state ^ (s * col_mask)
    # So:
    #   s = 0: new = old             (identity transition)
    #   s = 1: new = old ^ col_mask  (xor transition)
    #
    # Cost depends on whether s matches cover_bit (no flip → cost 0) or
    # not (flip → cost flip_cost). Therefore for each NEW state s', the
    # two incoming edges correspond to s = 0 and s = 1, and the cost of
    # each edge depends on cover_bit:
    #
    #   cover_bit = 0:
    #     s = 0: cost 0,         old = s'           (new = old → s' = old)
    #     s = 1: cost flip_cost, old = s' ^ col_mask (new = old ^ col_mask → s')
    #
    #   cover_bit = 1:
    #     s = 0: cost flip_cost, old = s'           (same shape as identity)
    #     s = 1: cost 0,         old = s' ^ col_mask (no-flip xor)

    for i in range(n):
        sub_col = i % w
        cover_bit = int(cover_lsbs[i])
        flip_cost = float(costs[i])
        xor_perm = xor_table[sub_col]

        # Edge "stego = 0": old = s'.            cost = (cover_bit == 0 ? 0 : flip_cost)
        # Edge "stego = 1": old = s' ^ col_mask. cost = (cover_bit == 1 ? 0 : flip_cost)
        extra_for_s0 = 0.0 if cover_bit == 0 else flip_cost
        extra_for_s1 = 0.0 if cover_bit == 1 else flip_cost

        cost_s0 = path_cost + extra_for_s0                # incoming from old = s'
        cost_s1 = path_cost[xor_perm] + extra_for_s1      # incoming from old = s' ^ col_mask

        # Min-of-two: which stego LSB gives lower cost for each new state s'.
        choose_s1 = cost_s1 < cost_s0
        new_cost = np.where(choose_s1, cost_s1, cost_s0)

        # Record the chosen stego LSB at this step for each new state.
        path_choice[i] = np.where(choose_s1, 1, 0).astype(np.uint8)

        # Syndrome boundary: every w cover bits, consume one message bit.
        if (i + 1) % w == 0:
            msg_idx = (i + 1) // w - 1
            target_lsb = int(message[msg_idx])
            # Only states with matching LSB survive, then shift right.
            shifted = np.full(num_states, INF, dtype=np.float64)
            valid_mask = ((state_idx & 1) == target_lsb)
            valid_states = np.where(valid_mask)[0]
            new_states_after_shift = valid_states >> 1
            # Multiple old states may map to same shifted state — take min.
            for old_s, new_s in zip(valid_states, new_states_after_shift):
                if new_cost[old_s] < shifted[new_s]:
                    shifted[new_s] = new_cost[old_s]
            path_cost = shifted
        else:
            path_cost = new_cost

    # End of forward pass: only state 0 is a valid terminal state (all
    # syndromes consumed, no leftover partial syndrome).
    final_cost = path_cost[0]
    if not np.isfinite(final_cost):
        raise ValueError("STC encoding failed: no valid path. Verify cover/message dimensions.")

    # Backward traceback.
    # At end of forward pass, after the final shift, we landed at state 0.
    # Therefore the pre-shift state of the LAST block had LSB = message[m-1]
    # and (state >> 1) == 0, so pre-shift state = message[m-1].
    stego_lsbs = np.zeros(n, dtype=np.uint8)
    current_state = int(message[m - 1])

    # Walk backwards. Invariant: at the start of iteration i, `current_state`
    # is the state recorded *after* processing cover bit i during forward
    # pass (i.e. before any syndrome-boundary shift). Therefore
    # `path_choice[i, current_state]` gives the stego LSB chosen at step i.
    for i in range(n - 1, -1, -1):
        sub_col = i % w
        col_mask = int(sub_matrix[sub_col])

        stego = int(path_choice[i, current_state])
        stego_lsbs[i] = stego

        # Undo the state transition for step i:
        #   new_state = old_state ^ (stego * col_mask)
        # so old_state = new_state ^ (stego * col_mask).
        if stego == 1:
            current_state ^= col_mask

        # If we just stepped into position 0 of block (i // w), then
        # `current_state` is now the state at the *start* of this block,
        # i.e. the post-shift state of the previous block. Reverse the shift
        # to recover that previous block's pre-shift state.
        if i > 0 and i % w == 0:
            msg_idx = i // w - 1
            target_lsb = int(message[msg_idx])
            current_state = (current_state << 1) | target_lsb

    if current_state != 0:
        raise ValueError(
            f"STC traceback inconsistency: walked back to state {current_state} "
            f"instead of 0 — implementation bug."
        )

    return stego_lsbs


# -----------------------------------------------------------------------------
# Decoder
# -----------------------------------------------------------------------------

def stc_decode(
    stego_lsbs: np.ndarray,
    m: int,
    sub_matrix: Sequence[int] = STC_SUBMATRIX_V1,
    h: int = STC_H_V1,
) -> np.ndarray:
    """Returns the m-bit syndrome / message recovered from `stego_lsbs`.

    The decoder is a single linear pass: each stego LSB at position i, if it
    is 1, XOR-contributes the bits of `sub_matrix[i mod w]` into the message
    starting at syndrome position floor(i/w).
    """
    stego_lsbs = np.asarray(stego_lsbs, dtype=np.uint8)
    w = len(sub_matrix)
    n = stego_lsbs.shape[0]
    if n != w * m:
        raise ValueError(f"stego length {n} != w*m = {w*m}")

    message = np.zeros(m, dtype=np.uint8)
    for i in range(n):
        if stego_lsbs[i] == 0:
            continue
        sub_col = i % w
        col_mask = int(sub_matrix[sub_col])
        msg_idx_base = i // w
        # XOR col_mask bits into message positions msg_idx_base..msg_idx_base+h-1
        for r in range(h):
            if msg_idx_base + r >= m:
                break
            if (col_mask >> r) & 1:
                message[msg_idx_base + r] ^= 1
    return message


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
        n = w * m                            # cover length

        cover = rng.integers(0, 2, n, dtype=np.uint8)
        costs = rng.random(n, dtype=np.float64) + 0.1
        message = rng.integers(0, 2, m, dtype=np.uint8)

        stego = stc_encode(cover, costs, message, submatrix, h)
        recovered = stc_decode(stego, m, submatrix, h)

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
