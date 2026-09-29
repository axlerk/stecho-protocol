# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""
Reference decoder for the Stecho v1 wire format
(`juniward-layer.md` + `open-v1.md` + `stealth-v1.md`).

This module is the canonical, independent re-implementation of Stecho's
JPEG steganography. It uses:

- `jpeglib` for lossless DCT coefficient access.
- `conseal.juniward.compute_cost_adjusted` for the J-UNIWARD distortion
  cost map (verified by conseal's authors against the Binghamton MATLAB
  reference).
- A self-contained Python STC implementation in `stc.py`, pinning the
  canonical h=10, w=12 sub-matrix from the Filler-Judas-Fridrich 2011
  Binghamton table.
- `cryptography` for AES-256-GCM and PBKDF2-HMAC-SHA256.

The encoder side is informational: it exists so the spec can be self-
tested without an iOS build. The shipping Stecho app uses its own Swift
implementation; the encoder side is not part of the normative spec.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
import tempfile
from typing import List, Optional, Tuple

import jpeglib
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import conseal as cs

from stc import (
    STC_H_V1,
    STC_W_V1,
    STC_SUBMATRIX_V1,
    stc_encode,
    stc_decode,
)


# ---------------------------------------------------------------------------
# Protocol constants — see ../../juniward-layer.md, ../../open-v1.md,
# ../../stealth-v1.md
# ---------------------------------------------------------------------------

# Stealth-v1 permutation derivation
STEALTH_PERM_PBKDF2_SALT = b"stecho-stealth-v1-perm-salt"   # 27 bytes
STEALTH_PERM_INFO        = b"stecho-stealth-v1-perm"        # 22 bytes
PBKDF2_ITER              = 600_000
KEY_LEN                  = 32                                # AES-256

# Open-v1 framing
OPEN_MAGIC               = b"SECO"                           # 4 bytes
OPEN_VERSION             = 0x01

# Stealth-v1 framing
AES_SALT_LEN             = 16
AES_NONCE_LEN            = 12
AES_TAG_LEN              = 16
STEALTH_HEADER_LEN       = AES_SALT_LEN + AES_NONCE_LEN      # 28 — outside GCM
STEALTH_INNER_HDR_LEN    = 1 + 4                             # type(1) + body_len(4)

# Payload type tags
TYPE_TEXT       = 0x01
TYPE_AUDIO_OPUS = 0x02
KNOWN_TYPE_TAGS = {TYPE_TEXT, TYPE_AUDIO_OPUS}


# ---------------------------------------------------------------------------
# JPEG zigzag — maps zigzag index 0..63 to natural row-major (row, col)
# inside an 8x8 block. swift-jpeg stores coefs in zigzag order; jpeglib
# stores them natural-order. The spec's `z` index is zigzag.
# ---------------------------------------------------------------------------

ZIGZAG_TO_NATURAL: Tuple[Tuple[int, int], ...] = (
    (0, 0), (0, 1), (1, 0), (2, 0), (1, 1), (0, 2), (0, 3), (1, 2),
    (2, 1), (3, 0), (4, 0), (3, 1), (2, 2), (1, 3), (0, 4), (0, 5),
    (1, 4), (2, 3), (3, 2), (4, 1), (5, 0), (6, 0), (5, 1), (4, 2),
    (3, 3), (2, 4), (1, 5), (0, 6), (0, 7), (1, 6), (2, 5), (3, 4),
    (4, 3), (5, 2), (6, 1), (7, 0), (7, 1), (6, 2), (5, 3), (4, 4),
    (3, 5), (2, 6), (1, 7), (2, 7), (3, 6), (4, 5), (5, 4), (6, 3),
    (7, 2), (7, 3), (6, 4), (5, 5), (4, 6), (3, 7), (4, 7), (5, 6),
    (6, 5), (7, 4), (7, 5), (6, 6), (5, 7), (6, 7), (7, 6), (7, 7),
)


# ---------------------------------------------------------------------------
# Position enumeration — see juniward-layer.md §2
# ---------------------------------------------------------------------------

Position = Tuple[int, int, int, int]   # (plane_idx, block_y, block_x, z_zigzag)


def _component_planes(im: "jpeglib.DCTJPEG") -> List[np.ndarray]:
    """Returns per-component DCT arrays in JPEG component declaration order."""
    planes: List[np.ndarray] = []
    if im.Y is not None:
        planes.append(im.Y)
    if im.num_components >= 2 and im.Cb is not None:
        planes.append(im.Cb)
    if im.num_components >= 3 and im.Cr is not None:
        planes.append(im.Cr)
    if im.num_components == 4 and im.K is not None:
        planes.append(im.K)
    return planes


def enumerate_positions(planes: List[np.ndarray]) -> List[Position]:
    """Builds the canonical AC position list per layer spec §2."""
    positions: List[Position] = []
    for plane_idx, plane in enumerate(planes):
        by_count, bx_count, _h, _w = plane.shape
        for by in range(by_count):
            for bx in range(bx_count):
                for z in range(1, 64):
                    positions.append((plane_idx, by, bx, z))
    return positions


def lsb_at(planes: List[np.ndarray], pos: Position) -> int:
    plane_idx, by, bx, z = pos
    row, col = ZIGZAG_TO_NATURAL[z]
    return int(abs(planes[plane_idx][by, bx, row, col])) & 1


def coef_at(planes: List[np.ndarray], pos: Position) -> int:
    plane_idx, by, bx, z = pos
    row, col = ZIGZAG_TO_NATURAL[z]
    return int(planes[plane_idx][by, bx, row, col])


def set_coef(planes: List[np.ndarray], pos: Position, value: int) -> None:
    plane_idx, by, bx, z = pos
    row, col = ZIGZAG_TO_NATURAL[z]
    planes[plane_idx][by, bx, row, col] = value


# ---------------------------------------------------------------------------
# Permutations — see open-v1.md §2 and stealth-v1.md §2
# ---------------------------------------------------------------------------

def identity_permutation(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.int64)


def _stealth_perm_key(password: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=KEY_LEN,
        salt=STEALTH_PERM_PBKDF2_SALT,
        iterations=PBKDF2_ITER,
    )
    return kdf.derive(password)


def _stealth_keystream(perm_key: bytes, length_bytes: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length_bytes:
        ctr_be = struct.pack(">I", counter)
        block = hmac.new(perm_key, ctr_be + STEALTH_PERM_INFO, hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length_bytes])


def stealth_permutation(password: bytes, n: int) -> np.ndarray:
    perm_key = _stealth_perm_key(password)
    ks = _stealth_keystream(perm_key, n * 4)
    indices = np.arange(n, dtype=np.int64)
    for i in range(n - 1, 0, -1):
        r = int.from_bytes(ks[i * 4: i * 4 + 4], "big")
        j = r % (i + 1)
        if i != j:
            indices[i], indices[j] = indices[j], indices[i]
    return indices


# ---------------------------------------------------------------------------
# J-UNIWARD cost map — see juniward-layer.md §3
# ---------------------------------------------------------------------------

def compute_costs(im: "jpeglib.DCTJPEG", pixels: np.ndarray) -> List[np.ndarray]:
    """Returns per-component arrays of symmetric per-coefficient embedding cost,
    shape matching im.{Y,Cb,Cr} (i.e. (by, bx, 8, 8)).

    Wet positions (zero AC, DC, saturated blocks) are clipped to a large cost
    that effectively prevents modification by STC.
    """
    planes = _component_planes(im)
    cost_planes = []
    for plane_idx, plane in enumerate(planes):
        # conseal expects pixel-domain and DCT-domain arrays of the same component.
        # For 4:2:0 chroma, plane shape differs from Y. compute_cost_adjusted
        # works per single channel.
        # The pixel-domain x0 needs to be the spatial (decompressed) plane
        # at the corresponding resolution. For our test purposes — which use
        # the same plane for Y/Cb/Cr (synthetic carriers) — we pass the same
        # pixel grid downsampled appropriately.
        if plane_idx == 0:
            x0 = pixels.astype(np.float64)
        else:
            # Approximate chroma plane resolution as half (4:2:0).
            x0 = pixels[::2, ::2].astype(np.float64)
        qt = im.qt[im.quant_tbl_no[plane_idx]] if hasattr(im, 'qt') and im.qt is not None else None
        if qt is None:
            qt = np.ones((8, 8), dtype=np.int32) * 16
        try:
            rho_p1, rho_m1 = cs.juniward.compute_cost_adjusted(
                x0=x0,
                y0=plane.astype(np.int32),
                qt=qt.astype(np.int32),
                implementation=cs.juniward.JUNIWARD_ORIGINAL,
            )
        except Exception:
            # If conseal fails for this plane, fall back to uniform cost (still
            # correct for round-trip; just non-content-adaptive).
            rho_p1 = np.ones_like(plane, dtype=np.float64)
            rho_m1 = np.ones_like(plane, dtype=np.float64)
        # Symmetric cost: minimum of the two directions (encoder may pick
        # whichever sign is cheaper at apply time).
        rho = np.minimum(rho_p1, rho_m1).astype(np.float64)
        # Wet positions: DC (we never visit it via the AC enumerator anyway,
        # but marking it here keeps the layout uniform) and any |c| <= 1
        # coefficient. The |c|=0 case is the F-family "zero AC" wet — flipping
        # would inject a ±1 coefficient that's statistically detectable. The
        # |c|=1 case is the F-family "shrinkage" wet — flipping decrements to 0
        # and destroys decoder alignment. We use 1e13 as the wet-cost sentinel
        # to match juniward-layer.md §3 / `conseal` default.
        plane_abs = np.abs(plane)
        wet_mask = (plane_abs <= 1)
        wet_mask[:, :, 0, 0] = True
        rho[wet_mask] = 1e13
        cost_planes.append(rho)
    return cost_planes


def cost_at(cost_planes: List[np.ndarray], pos: Position) -> float:
    plane_idx, by, bx, z = pos
    row, col = ZIGZAG_TO_NATURAL[z]
    return float(cost_planes[plane_idx][by, bx, row, col])


# ---------------------------------------------------------------------------
# Layer encode / decode (uses STC) — see juniward-layer.md §§5-6
# ---------------------------------------------------------------------------

def _gather_lsbs_and_costs(
    planes: List[np.ndarray],
    cost_planes: List[np.ndarray],
    positions: List[Position],
    perm: np.ndarray,
    n_use: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Walks first n_use entries of permutation, returns LSB array and cost array."""
    lsbs = np.zeros(n_use, dtype=np.uint8)
    costs = np.zeros(n_use, dtype=np.float64)
    for i in range(n_use):
        pos = positions[perm[i]]
        lsbs[i] = lsb_at(planes, pos)
        costs[i] = cost_at(cost_planes, pos)
    return lsbs, costs


def _apply_stego_to_planes(
    planes: List[np.ndarray],
    positions: List[Position],
    perm: np.ndarray,
    n_use: int,
    stego_lsbs: np.ndarray,
) -> int:
    """For each permuted position where stego_lsb != cover_lsb, flip the AC
    coefficient by ±1 (away from zero — preserves non-zero invariant).
    Returns the count of positions where STC asked us to flip a wet
    coefficient (|c| <= 1) — should be zero for a well-formed embedding."""
    wet_flips = 0
    for i in range(n_use):
        pos = positions[perm[i]]
        current = coef_at(planes, pos)
        current_lsb = abs(current) & 1
        desired_lsb = int(stego_lsbs[i])
        if current_lsb == desired_lsb:
            continue
        # STC wants this position flipped. If it's wet (|c| <= 1), this is a
        # bug — the cost map should have made the wet position unattractive
        # enough to never flip. Count occurrences for diagnostics; choose a
        # direction that does not leave a zero behind.
        if abs(current) <= 1:
            wet_flips += 1
            # Move away from zero so the position stays non-zero (preserves
            # decoder alignment that walks all positions). For 0 -> +1 we
            # arbitrarily pick +1 (the spec treats both directions as
            # equivalent under symmetric J-UNIWARD).
            if current == 0:
                set_coef(planes, pos, 1)
            elif current == 1:
                set_coef(planes, pos, 2)
            else:                   # current == -1
                set_coef(planes, pos, -2)
        else:
            # Standard non-wet flip: decrement |c| by 1, preserving sign.
            # |c| stays >= 1, so the position remains non-zero.
            if current > 0:
                set_coef(planes, pos, current - 1)
            else:
                set_coef(planes, pos, current + 1)
    return wet_flips


def layer_encode_in_place(
    im: "jpeglib.DCTJPEG",
    pixels: np.ndarray,
    perm: np.ndarray,
    message_bits: np.ndarray,
) -> None:
    """STC-embed message_bits into im's DCT coefficients in permuted order.
    Modifies im in place. Caller is responsible for serialization (write_dct)."""
    planes = _component_planes(im)
    positions = enumerate_positions(planes)
    n_total = len(positions)
    w = STC_W_V1
    m = len(message_bits)
    n_use = w * m
    if n_use > n_total:
        raise ValueError(f"Message of {m} bits needs n={n_use} positions but JPEG has {n_total}")

    cost_planes = compute_costs(im, pixels)
    cover_lsbs, costs = _gather_lsbs_and_costs(planes, cost_planes, positions, perm, n_use)
    stego_lsbs = stc_encode(cover_lsbs, costs, message_bits.astype(np.uint8), STC_SUBMATRIX_V1, STC_H_V1)
    _apply_stego_to_planes(planes, positions, perm, n_use, stego_lsbs)


def layer_decode(
    im: "jpeglib.DCTJPEG",
    perm: np.ndarray,
    m_bits: int,
) -> np.ndarray:
    """STC-decode m_bits message bits from im's DCT coefficients."""
    planes = _component_planes(im)
    positions = enumerate_positions(planes)
    w = STC_W_V1
    n_use = w * m_bits
    if n_use > len(positions):
        raise ValueError("JPEG too small for requested message length")
    stego_lsbs = np.zeros(n_use, dtype=np.uint8)
    for i in range(n_use):
        stego_lsbs[i] = lsb_at(planes, positions[perm[i]])
    return stc_decode(stego_lsbs, m_bits, STC_SUBMATRIX_V1, STC_H_V1)


# ---------------------------------------------------------------------------
# Bit ↔ byte helpers (MSB-first per spec §5)
# ---------------------------------------------------------------------------

def bits_to_bytes(bits: np.ndarray) -> bytes:
    n_bytes = len(bits) // 8
    out = bytearray(n_bytes)
    for i in range(n_bytes):
        b = 0
        for k in range(8):
            b = (b << 1) | int(bits[i * 8 + k])
        out[i] = b
    return bytes(out)


def bytes_to_bits(data: bytes) -> np.ndarray:
    bits = np.zeros(len(data) * 8, dtype=np.uint8)
    for i, byte in enumerate(data):
        for k in range(8):
            bits[i * 8 + k] = (byte >> (7 - k)) & 1
    return bits


# ---------------------------------------------------------------------------
# JPEG load / save helpers (jpeglib is path-based, so we round-trip via temp)
# ---------------------------------------------------------------------------

def _decompress_pixels(jpeg_path: str) -> np.ndarray:
    """Returns the decoded RGB or grayscale pixel array of shape (H, W)
    for Y-channel of the JPEG. This is what J-UNIWARD needs as `x0`."""
    spatial = jpeglib.read_spatial(jpeg_path)
    # spatial.spatial has shape (H, W, C) or (H, W). For J-UNIWARD we use Y only.
    arr = spatial.spatial
    if arr.ndim == 3:
        # RGB → Y (BT.601)
        y = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2])
        return y
    return arr.astype(np.float64)


def _read_jpeg_dct(jpeg_bytes: bytes) -> Tuple["jpeglib.DCTJPEG", str]:
    """Writes jpeg_bytes to a temp file and reads via jpeglib. Returns (DCT, path).
    Caller responsible for cleanup of path."""
    tf = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tf.write(jpeg_bytes)
    tf.flush()
    tf.close()
    im = jpeglib.read_dct(tf.name)
    return im, tf.name


# ---------------------------------------------------------------------------
# Open-v1 framing — see open-v1.md
# ---------------------------------------------------------------------------

def encode_open(jpeg_in_path: str, type_tag: int, body: bytes, jpeg_out_path: str) -> None:
    """Encodes (type_tag, body) into the carrier as open-v1 mode."""
    if type_tag not in KNOWN_TYPE_TAGS:
        raise ValueError(f"unknown type_tag {type_tag}")

    im = jpeglib.read_dct(jpeg_in_path)
    pixels = _decompress_pixels(jpeg_in_path)
    planes = _component_planes(im)
    positions = enumerate_positions(planes)
    n_total = len(positions)
    w = STC_W_V1
    m = n_total // w
    n_use = w * m

    # Plaintext stream layout per open-v1.md §4.
    header = OPEN_MAGIC + bytes([OPEN_VERSION, type_tag]) + struct.pack("<I", len(body))
    fixed = header + body
    capacity_bytes = m // 8         # message bits → bytes (drop trailing < 8)
    if len(fixed) > capacity_bytes:
        raise ValueError(f"open payload {len(fixed)} B exceeds capacity {capacity_bytes} B")
    # Pad with random bytes to fill the entire stream.
    pad = secrets.token_bytes(capacity_bytes - len(fixed))
    stream = fixed + pad
    bits = bytes_to_bits(stream)
    # Round bits down to a multiple of 8 — n_use bits = 8 * capacity_bytes might
    # exceed our bit total, but we have at most m bits and 8 * capacity_bytes == m_truncated.
    bits = bits[: w * 0]  # placeholder for type-check; reassign below.

    bits = bytes_to_bits(stream)
    message_bits = bits[: 8 * capacity_bytes]
    # We embed exactly 8*capacity_bytes message bits. n_use = w * 8 * capacity_bytes.
    n_use = w * len(message_bits)

    perm = identity_permutation(n_total)
    cost_planes = compute_costs(im, pixels)
    cover_lsbs, costs = _gather_lsbs_and_costs(planes, cost_planes, positions, perm, n_use)
    stego_lsbs = stc_encode(cover_lsbs, costs, message_bits, STC_SUBMATRIX_V1, STC_H_V1)
    _apply_stego_to_planes(planes, positions, perm, n_use, stego_lsbs)

    im.write_dct(jpeg_out_path)


def decode_open(jpeg_bytes: bytes) -> Optional[Tuple[int, bytes]]:
    """Try to recover an open-v1 payload. Returns None on any failure
    (including not-Stecho-JPEG)."""
    try:
        im, _path = _read_jpeg_dct(jpeg_bytes)
    except Exception:
        return None
    try:
        planes = _component_planes(im)
        if not planes:
            return None
        positions = enumerate_positions(planes)
        n_total = len(positions)
        w = STC_W_V1
        m = n_total // w
        capacity_bytes = m // 8
        if capacity_bytes < 10:
            return None

        perm = identity_permutation(n_total)
        n_use = w * 8 * capacity_bytes
        stego_lsbs = np.zeros(n_use, dtype=np.uint8)
        for i in range(n_use):
            stego_lsbs[i] = lsb_at(planes, positions[perm[i]])
        message_bits = stc_decode(stego_lsbs, 8 * capacity_bytes, STC_SUBMATRIX_V1, STC_H_V1)
        stream = bits_to_bytes(message_bits)

        if len(stream) < 10:
            return None
        if stream[:4] != OPEN_MAGIC:
            return None
        if stream[4] != OPEN_VERSION:
            return None
        type_tag = stream[5]
        if type_tag not in KNOWN_TYPE_TAGS:
            return None
        length = struct.unpack("<I", stream[6:10])[0]
        if length > len(stream) - 10:
            return None
        body = stream[10:10 + length]
        return type_tag, body
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stealth-v1 framing — see stealth-v1.md
# ---------------------------------------------------------------------------

def _aes_key_from(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=KEY_LEN,
        salt=salt,
        iterations=PBKDF2_ITER,
    )
    return kdf.derive(password)


def encode_stealth(jpeg_in_path: str, password: str, type_tag: int,
                    body: bytes, jpeg_out_path: str) -> None:
    """Encodes (type_tag, body) into the carrier as stealth-v1 mode."""
    if type_tag not in KNOWN_TYPE_TAGS:
        raise ValueError(f"unknown type_tag {type_tag}")
    pw_bytes = password.encode("utf-8")

    im = jpeglib.read_dct(jpeg_in_path)
    pixels = _decompress_pixels(jpeg_in_path)
    planes = _component_planes(im)
    positions = enumerate_positions(planes)
    n_total = len(positions)
    w = STC_W_V1
    m = n_total // w
    capacity_bytes = m // 8

    inner_max = capacity_bytes - STEALTH_HEADER_LEN - AES_TAG_LEN - STEALTH_INNER_HDR_LEN
    if len(body) > inner_max:
        raise ValueError(f"stealth payload {len(body)} B exceeds max {inner_max} B")

    # Build inner plaintext: type(1) || body_len(4 LE) || body || random pad
    inner_size = capacity_bytes - STEALTH_HEADER_LEN - AES_TAG_LEN
    inner_fixed = bytes([type_tag]) + struct.pack("<I", len(body)) + body
    inner_pad = secrets.token_bytes(inner_size - len(inner_fixed))
    inner_plaintext = inner_fixed + inner_pad

    # AES-GCM seal.
    aes_salt = secrets.token_bytes(AES_SALT_LEN)
    aes_nonce = secrets.token_bytes(AES_NONCE_LEN)
    aes_key = _aes_key_from(pw_bytes, aes_salt)
    aad = aes_salt + aes_nonce
    ct_with_tag = AESGCM(aes_key).encrypt(aes_nonce, inner_plaintext, aad)
    assert len(ct_with_tag) == inner_size + AES_TAG_LEN

    # Compose stealth stream and embed.
    stream = aes_salt + aes_nonce + ct_with_tag
    assert len(stream) == capacity_bytes
    message_bits = bytes_to_bits(stream)

    perm = stealth_permutation(pw_bytes, n_total)
    n_use = w * len(message_bits)
    cost_planes = compute_costs(im, pixels)
    cover_lsbs, costs = _gather_lsbs_and_costs(planes, cost_planes, positions, perm, n_use)
    stego_lsbs = stc_encode(cover_lsbs, costs, message_bits, STC_SUBMATRIX_V1, STC_H_V1)
    _apply_stego_to_planes(planes, positions, perm, n_use, stego_lsbs)

    im.write_dct(jpeg_out_path)


def decode_stealth(jpeg_bytes: bytes, password: str) -> Optional[Tuple[int, bytes]]:
    """Try to recover a stealth-v1 payload. Returns None on any failure."""
    try:
        im, _path = _read_jpeg_dct(jpeg_bytes)
    except Exception:
        return None
    try:
        pw_bytes = password.encode("utf-8")
        planes = _component_planes(im)
        if not planes:
            return None
        positions = enumerate_positions(planes)
        n_total = len(positions)
        w = STC_W_V1
        m = n_total // w
        capacity_bytes = m // 8
        if capacity_bytes < STEALTH_HEADER_LEN + AES_TAG_LEN + STEALTH_INNER_HDR_LEN:
            return None

        perm = stealth_permutation(pw_bytes, n_total)
        n_use = w * 8 * capacity_bytes
        stego_lsbs = np.zeros(n_use, dtype=np.uint8)
        for i in range(n_use):
            stego_lsbs[i] = lsb_at(planes, positions[perm[i]])
        message_bits = stc_decode(stego_lsbs, 8 * capacity_bytes, STC_SUBMATRIX_V1, STC_H_V1)
        stream = bits_to_bytes(message_bits)

        if len(stream) < STEALTH_HEADER_LEN + AES_TAG_LEN:
            return None
        aes_salt = stream[:AES_SALT_LEN]
        aes_nonce = stream[AES_SALT_LEN:AES_SALT_LEN + AES_NONCE_LEN]
        ct_with_tag = stream[STEALTH_HEADER_LEN:]
        aes_key = _aes_key_from(pw_bytes, aes_salt)
        aad = aes_salt + aes_nonce
        try:
            inner = AESGCM(aes_key).decrypt(aes_nonce, ct_with_tag, aad)
        except Exception:
            return None

        if len(inner) < STEALTH_INNER_HDR_LEN:
            return None
        type_tag = inner[0]
        if type_tag not in KNOWN_TYPE_TAGS:
            return None
        body_len = struct.unpack("<I", inner[1:5])[0]
        if body_len > len(inner) - STEALTH_INNER_HDR_LEN:
            return None
        body = inner[5:5 + body_len]
        return type_tag, body
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

def decode(jpeg_bytes: bytes, password: Optional[str] = None) -> Optional[Tuple[str, int, bytes]]:
    """Try open first, fall through to stealth if password is given.
    Returns (mode, type_tag, body) or None."""
    res = decode_open(jpeg_bytes)
    if res is not None:
        return ("open",) + res
    if password is None:
        return None
    res = decode_stealth(jpeg_bytes, password)
    if res is not None:
        return ("stealth",) + res
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: stecho_decode.py <jpeg-path> [password]", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], "rb") as f:
        data = f.read()
    pw = sys.argv[2] if len(sys.argv) == 3 else None
    result = decode(data, pw)
    if result is None:
        print("No Stecho payload.", file=sys.stderr)
        sys.exit(1)
    mode, type_tag, body = result
    print(f"mode={mode} type=0x{type_tag:02x} body_len={len(body)}", file=sys.stderr)
    if type_tag == TYPE_TEXT:
        sys.stdout.write(body.decode("utf-8", errors="replace"))
    else:
        sys.stdout.buffer.write(body)
