# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""
Reference encoder and decoder for the Stecho v2 wire format
(`juniward-layer.md` §V2 + `open-v2.md` + `stealth-v2.md`).

What changes from v1 (stecho_decode.py):

- The cover is the non-zero AC coefficients only, in the canonical v1 order.
  Embedding never creates or removes a zero (|c| = 1 that must change goes
  to 2), so the decoder enumerates the same set from the stego JPEG.
- Both modes walk the cover in a keyed permutation: public key in open mode,
  password-derived key in stealth mode.
- One ladder of five rates ("rungs") with one STC sub-matrix each; the
  encoder picks a rung, the decoder tries them in ascending order.
- J-UNIWARD costs are computed per component on that component's own
  decompressed plane (chroma at its own resolution).
- SI-UNIWARD is an encoder option when the encoder quantises the pixels
  itself (`encode_v2_from_pixels`). It does not change the wire format.

Decoding needs only jpeglib, numpy and cryptography; costs (conseal, scipy)
are encoder-only.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import struct
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import jpeglib
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from stc import STC_H_V1, block_widths, stc_decode_v2, stc_encode_v2
from stecho_decode import (
    AES_NONCE_LEN,
    AES_SALT_LEN,
    AES_TAG_LEN,
    KNOWN_TYPE_TAGS,
    OPEN_MAGIC,
    STEALTH_HEADER_LEN,
    STEALTH_INNER_HDR_LEN,
    ZIGZAG_TO_NATURAL,
    _aes_key_from,
    _component_planes,
    _stealth_perm_key,
    bits_to_bytes,
    bytes_to_bits,
)


# ---------------------------------------------------------------------------
# Protocol constants — juniward-layer.md §V2, open-v2.md, stealth-v2.md
# ---------------------------------------------------------------------------

STC_H_V2 = STC_H_V1   # 10

# The rate ladder: rung k (1-based) embeds q/d message bits per cover element.
RUNGS_V2: Tuple[Tuple[int, int], ...] = (
    (1, 40),   # rung 1: 0.025
    (1, 20),   # rung 2: 0.05
    (1, 10),   # rung 3: 0.1
    (1, 5),    # rung 4: 0.2
    (2, 5),    # rung 5: 0.4
)

# One sub-matrix per rung, ceil(d/q) columns of h = 10 bits, bit r of a
# column is row r. From stc_submatrix_search.py (seed 20261104); see
# juniward-layer.md §V2.6.3.
SUBMATRICES_V2: Tuple[Tuple[int, ...], ...] = (
    # rung 1 (0.025), 40 columns
    (
     795, 549, 989, 725, 1021, 535, 995, 843, 779, 777,
     615, 649, 729, 745, 841, 651, 905, 659, 981, 737,
     719, 701, 675, 661, 1003, 623, 787, 965, 991, 929,
     537, 917, 681, 913, 643, 705, 889, 671, 1013, 803,
    ),
    # rung 2 (0.05), 20 columns
    (
     745, 795, 779, 835, 805, 523, 889, 921, 589, 521,
     617, 569, 839, 767, 533, 575, 703, 989, 959, 535,
    ),
    # rung 3 (0.1), 10 columns
    (
     973, 827, 981, 813, 519, 741, 689, 887, 529, 603,
    ),
    # rung 4 (0.2), 5 columns
    (
     675, 985, 613, 917, 795,
    ),
    # rung 5 (0.4), 3 columns
    (
     535, 981, 883,
    ),
)

OPEN_VERSION_V2 = 0x02
OPEN_HEADER_LEN = 10                      # magic 4 + version 1 + type 1 + length 4
STEALTH_OVERHEAD = STEALTH_HEADER_LEN + AES_TAG_LEN + STEALTH_INNER_HDR_LEN   # 49

OPEN_PERM_KEY = hashlib.sha256(b"stecho-open-v2-perm-key").digest()
OPEN_PERM_INFO = b"stecho-open-v2-perm"
STEALTH_PERM_INFO_V2 = b"stecho-stealth-v2-perm"

# Largest |c| an 8-bit-precision JPEG can carry in an AC coefficient.
MAX_AC_MAGNITUDE = 1023

WET_COST = 1e13

# Zigzag index z = 1..63 -> natural (row, col).
_ZZ_ROW = np.array([ZIGZAG_TO_NATURAL[z][0] for z in range(1, 64)])
_ZZ_COL = np.array([ZIGZAG_TO_NATURAL[z][1] for z in range(1, 64)])


# ---------------------------------------------------------------------------
# Cover — juniward-layer.md §V2.3
# ---------------------------------------------------------------------------

@dataclass
class Cover:
    """The v2 cover: non-zero AC coefficients in canonical order.

    `plane[i]` and `flat[i]` locate element i in `planes[plane[i]].reshape(-1)`
    (natural (by, bx, row, col) layout, as jpeglib stores it)."""
    plane: np.ndarray
    flat: np.ndarray
    coef: np.ndarray

    @property
    def n(self) -> int:
        return int(self.coef.shape[0])


def cover_v2(planes: Sequence[np.ndarray]) -> Cover:
    plane_ids, flats, coefs = [], [], []
    for p, arr in enumerate(planes):
        by, bx = arr.shape[:2]
        # (by, bx, 63) in zigzag order z = 1..63, then flattened: the v1 order.
        zz = arr[:, :, _ZZ_ROW, _ZZ_COL].reshape(-1)
        nat = ((np.arange(by * bx)[:, None] * 64) + (_ZZ_ROW * 8 + _ZZ_COL)[None, :]).reshape(-1)
        keep = zz != 0
        plane_ids.append(np.full(int(keep.sum()), p, dtype=np.int64))
        flats.append(nat[keep])
        coefs.append(zz[keep].astype(np.int64))
    return Cover(np.concatenate(plane_ids), np.concatenate(flats), np.concatenate(coefs))


# ---------------------------------------------------------------------------
# Permutation — juniward-layer.md §V2.4
# ---------------------------------------------------------------------------

def keyed_permutation(key: bytes, info: bytes, n: int) -> np.ndarray:
    """Fisher-Yates over [0, n) driven by HMAC-SHA256(key, BE32(c) || info),
    the v1 construction with the key and info as parameters."""
    blocks = (n * 4 + 31) // 32
    ks = b"".join(hmac.new(key, struct.pack(">I", c) + info, hashlib.sha256).digest()
                  for c in range(blocks))
    r = np.frombuffer(ks[: n * 4], dtype=">u4").astype(np.int64)
    idx = list(range(n))
    for i in range(n - 1, 0, -1):
        j = int(r[i]) % (i + 1)
        idx[i], idx[j] = idx[j], idx[i]
    return np.array(idx, dtype=np.int64)


def open_permutation(n: int) -> np.ndarray:
    return keyed_permutation(OPEN_PERM_KEY, OPEN_PERM_INFO, n)


def stealth_permutation_v2(perm_key: bytes, n: int) -> np.ndarray:
    return keyed_permutation(perm_key, STEALTH_PERM_INFO_V2, n)


# ---------------------------------------------------------------------------
# Rungs — juniward-layer.md §V2.5
# ---------------------------------------------------------------------------

@dataclass
class RungLayout:
    rung: int
    stream_bytes: int      # L
    widths: np.ndarray     # block widths, len = 8L
    n_use: int             # cover elements spanned, sum(widths) <= n


def rung_layout(n: int, rung: int) -> RungLayout:
    q, d = RUNGS_V2[rung - 1]
    stream_bytes = (n * q) // (8 * d)
    widths = block_widths(8 * stream_bytes, q, d)
    return RungLayout(rung, stream_bytes, widths, int(widths.sum()))


def submatrix(rung: int) -> Tuple[int, ...]:
    cols = SUBMATRICES_V2[rung - 1]
    q, d = RUNGS_V2[rung - 1]
    if len(cols) != -(-d // q):
        raise RuntimeError(f"sub-matrix of rung {rung} is not filled in")
    return cols


def open_capacity(n: int, rung: int) -> int:
    return rung_layout(n, rung).stream_bytes - OPEN_HEADER_LEN


def stealth_capacity(n: int, rung: int) -> int:
    return rung_layout(n, rung).stream_bytes - STEALTH_OVERHEAD


# ---------------------------------------------------------------------------
# Layer decode — juniward-layer.md §V2.8
# ---------------------------------------------------------------------------

def _permuted_lsbs(cover: Cover, perm: np.ndarray) -> np.ndarray:
    return (np.abs(cover.coef[perm]) & 1).astype(np.uint8)


def layer_decode_v2(lsbs_in_perm_order: np.ndarray, layout: RungLayout) -> bytes:
    bits = stc_decode_v2(lsbs_in_perm_order[: layout.n_use], submatrix(layout.rung),
                         layout.widths, STC_H_V2)
    return bits_to_bytes(bits)


def _read_dct(jpeg_bytes: bytes):
    import tempfile
    tf = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    try:
        tf.write(jpeg_bytes)
        tf.close()
        return jpeglib.read_dct(tf.name)
    finally:
        os.unlink(tf.name)


def _parse_open_stream(stream: bytes) -> Optional[Tuple[int, bytes]]:
    if len(stream) < OPEN_HEADER_LEN:
        return None
    if stream[:4] != OPEN_MAGIC or stream[4] != OPEN_VERSION_V2:
        return None
    type_tag = stream[5]
    if type_tag not in KNOWN_TYPE_TAGS:
        return None
    length = struct.unpack("<I", stream[6:10])[0]
    if length > len(stream) - OPEN_HEADER_LEN:
        return None
    return type_tag, stream[OPEN_HEADER_LEN:OPEN_HEADER_LEN + length]


def _open_stealth_stream(stream: bytes, password: bytes) -> Optional[Tuple[int, bytes]]:
    salt = stream[:AES_SALT_LEN]
    nonce = stream[AES_SALT_LEN:STEALTH_HEADER_LEN]
    key = _aes_key_from(password, salt)
    try:
        inner = AESGCM(key).decrypt(nonce, stream[STEALTH_HEADER_LEN:], salt + nonce)
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
    return type_tag, inner[STEALTH_INNER_HDR_LEN:STEALTH_INNER_HDR_LEN + body_len]


def decode_open_v2(jpeg_bytes: bytes) -> Optional[Tuple[int, int, bytes]]:
    """(rung, type_tag, body) of an open-v2 payload, or None."""
    try:
        cover = cover_v2(_component_planes(_read_dct(jpeg_bytes)))
        lsbs = _permuted_lsbs(cover, open_permutation(cover.n))
        for rung in range(1, len(RUNGS_V2) + 1):
            layout = rung_layout(cover.n, rung)
            if layout.stream_bytes < OPEN_HEADER_LEN:
                continue
            got = _parse_open_stream(layer_decode_v2(lsbs, layout))
            if got is not None:
                return (rung,) + got
    except Exception:
        return None
    return None


def decode_stealth_v2(jpeg_bytes: bytes, password: str,
                      perm_key: Optional[bytes] = None) -> Optional[Tuple[int, int, bytes]]:
    """(rung, type_tag, body) of a stealth-v2 payload, or None. `perm_key`
    may be passed in to share one PBKDF2 run with a stealth-v1 attempt."""
    try:
        pw = password.encode("utf-8")
        cover = cover_v2(_component_planes(_read_dct(jpeg_bytes)))
        if perm_key is None:
            perm_key = _stealth_perm_key(pw)
        lsbs = _permuted_lsbs(cover, stealth_permutation_v2(perm_key, cover.n))
        for rung in range(1, len(RUNGS_V2) + 1):
            layout = rung_layout(cover.n, rung)
            if layout.stream_bytes < STEALTH_OVERHEAD:
                continue
            got = _open_stealth_stream(layer_decode_v2(lsbs, layout), pw)
            if got is not None:
                return (rung,) + got
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Costs (encoder only) — juniward-layer.md §V2.9
# ---------------------------------------------------------------------------

def decompress_plane(coef: np.ndarray, qt: np.ndarray) -> np.ndarray:
    """One component's own spatial plane: dequantise, orthonormal 8x8 IDCT,
    +128, round, clip to [0, 255]. Shape (by*8, bx*8), chroma at its own size."""
    from scipy.fft import idctn
    by, bx = coef.shape[:2]
    blocks = idctn(coef.astype(np.float64) * qt[None, None].astype(np.float64),
                   axes=(2, 3), norm="ortho")
    px = blocks.transpose(0, 2, 1, 3).reshape(by * 8, bx * 8)
    return np.clip(np.round(px + 128), 0, 255).astype(np.uint8)


def _juniward(x0: np.ndarray, qt: np.ndarray) -> np.ndarray:
    import conseal as cs
    return cs.juniward._costmap.compute_cost(
        x0=x0, qt=qt.astype(np.uint16),
        implementation=cs.juniward.Implementation.JUNIWARD_ORIGINAL)


def _saturated_blocks(x0: np.ndarray) -> np.ndarray:
    h, w = x0.shape
    bl = x0.reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3)
    return ((bl == 0) | (bl == 255)).any(axis=(2, 3))


# SI-UNIWARD: modes whose rounding error of exactly 1/2 is common for integer
# pixels (they sit on a 1/8 grid) and would get zero cost; made wet.
_SI_DEGENERATE = ((0, 4), (4, 0), (4, 4))


def plane_costs(coef: np.ndarray, qt: np.ndarray, rng: np.random.Generator,
                precover: Optional[np.ndarray] = None,
                unquantised: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
    """Per coefficient of one plane: (cost of a parity change, direction).

    Direction is +1 (|c| grows) or -1 (|c| shrinks). Without side information
    it is J-UNIWARD (symmetric cost, random direction for |c| >= 2). With the
    precover and the unquantised values u it is SI-UNIWARD: cost scaled by
    (1 - 2|e|), e = u - c, moving toward u where that keeps c non-zero."""
    mag = np.abs(coef)
    x0 = decompress_plane(coef, qt)
    sat = _saturated_blocks(x0)
    if precover is None:
        rho = _juniward(x0, qt)
        grow = rng.random(coef.shape) < 0.5
    else:
        rho_p = _juniward(precover.astype(np.uint8), qt)
        e = unquantised - coef
        toward = np.sign(e)
        sgn = np.sign(coef)
        toward_grows = toward == sgn
        blocked = (mag == 1) & ~toward_grows & (toward != 0)
        rho = np.where(blocked | (e == 0), rho_p, (1 - 2 * np.abs(e)) * rho_p)
        grow = np.where(e == 0, rng.random(coef.shape) < 0.5, toward_grows)
        for (r, s) in _SI_DEGENERATE:
            half = np.abs(np.abs(e[:, :, r, s]) - 0.5) < 1e-9
            rho[:, :, r, s][half] = WET_COST
    grow = grow | (mag == 1)
    grow = grow & (mag < MAX_AC_MAGNITUDE)
    rho = np.where(np.isfinite(rho), rho, WET_COST)
    rho = np.minimum(rho, WET_COST)
    rho[sat] = WET_COST
    return rho, np.where(grow, 1, -1)


# ---------------------------------------------------------------------------
# Encoder (informative) — juniward-layer.md §V2.9, open-v2.md §6, stealth-v2.md §4-5
# ---------------------------------------------------------------------------

def choose_rung(n: int, mode: str, body_len: int, max_rung: int) -> int:
    for rung in range(1, max_rung + 1):
        cap = open_capacity(n, rung) if mode == "open" else stealth_capacity(n, rung)
        if body_len <= cap:
            return rung
    raise ValueError(f"{mode} payload of {body_len} B does not fit up to rung {max_rung}")


def build_open_stream(type_tag: int, body: bytes, stream_bytes: int) -> bytes:
    fixed = OPEN_MAGIC + bytes([OPEN_VERSION_V2, type_tag]) + struct.pack("<I", len(body)) + body
    return fixed + secrets.token_bytes(stream_bytes - len(fixed))


def build_stealth_stream(password: bytes, type_tag: int, body: bytes, stream_bytes: int) -> bytes:
    inner_size = stream_bytes - STEALTH_HEADER_LEN - AES_TAG_LEN
    inner = bytes([type_tag]) + struct.pack("<I", len(body)) + body
    inner += secrets.token_bytes(inner_size - len(inner))
    salt = secrets.token_bytes(AES_SALT_LEN)
    nonce = secrets.token_bytes(AES_NONCE_LEN)
    ct = AESGCM(_aes_key_from(password, salt)).encrypt(nonce, inner, salt + nonce)
    stream = salt + nonce + ct
    if len(stream) != stream_bytes:
        raise AssertionError("stealth stream size")
    return stream


@dataclass
class EncodeReport:
    rung: int
    n: int
    stream_bytes: int
    changes: int
    one_to_two: int
    wet_changes: int


def _embed(planes: List[np.ndarray], qts: List[np.ndarray], mode: str, type_tag: int,
           body: bytes, password: Optional[str], max_rung: int, rung: Optional[int],
           side_info: Optional[List[Tuple[np.ndarray, np.ndarray]]],
           rng: np.random.Generator) -> EncodeReport:
    if type_tag not in KNOWN_TYPE_TAGS:
        raise ValueError(f"unknown type_tag {type_tag}")
    if mode not in ("open", "stealth"):
        raise ValueError(f"unknown mode {mode}")
    cover = cover_v2(planes)
    n = cover.n
    if rung is None:
        rung = choose_rung(n, mode, len(body), max_rung)
    layout = rung_layout(n, rung)
    if mode == "open":
        if len(body) > open_capacity(n, rung):
            raise ValueError("open payload does not fit the rung")
        stream = build_open_stream(type_tag, body, layout.stream_bytes)
        perm = open_permutation(n)
    else:
        if not password:
            raise ValueError("stealth mode needs a non-empty password")
        pw = password.encode("utf-8")
        if len(body) > stealth_capacity(n, rung):
            raise ValueError("stealth payload does not fit the rung")
        stream = build_stealth_stream(pw, type_tag, body, layout.stream_bytes)
        perm = stealth_permutation_v2(_stealth_perm_key(pw), n)

    # Costs and change directions per plane, gathered into cover order.
    rho_flat, dir_flat = [], []
    for p, (coef, qt) in enumerate(zip(planes, qts)):
        si = side_info[p] if side_info is not None else (None, None)
        rho, direction = plane_costs(coef, qt, rng, precover=si[0], unquantised=si[1])
        rho_flat.append(rho.reshape(-1))
        dir_flat.append(direction.reshape(-1))
    offsets = np.cumsum([0] + [r.shape[0] for r in rho_flat])[:-1]
    where = offsets[cover.plane] + cover.flat
    rho = np.concatenate(rho_flat)[where]
    direction = np.concatenate(dir_flat)[where]

    use = perm[: layout.n_use]
    cover_lsbs = (np.abs(cover.coef[use]) & 1).astype(np.uint8)
    stego_lsbs = stc_encode_v2(cover_lsbs, rho[use], bytes_to_bits(stream),
                               submatrix(rung), layout.widths, STC_H_V2)
    changed = use[stego_lsbs != cover_lsbs]

    one_to_two = 0
    for i in changed:
        p, f = int(cover.plane[i]), int(cover.flat[i])
        flat = planes[p].reshape(-1)
        c = int(flat[f])
        if c != int(cover.coef[i]):
            raise AssertionError("cover element changed twice")
        mag = abs(c) + int(direction[i])
        if not 1 <= mag <= MAX_AC_MAGNITUDE:
            raise AssertionError("change would leave the non-zero set")
        one_to_two += abs(c) == 1
        flat[f] = mag if c > 0 else -mag

    # v2 invariants: same non-zero set, same order, parity flipped exactly
    # where STC asked, and the stream reads back.
    after = cover_v2(planes)
    if after.n != n or not np.array_equal(after.flat, cover.flat) or \
            not np.array_equal(after.plane, cover.plane):
        raise AssertionError("v2 invariant broken: non-zero set changed")
    if layer_decode_v2(_permuted_lsbs(after, perm), layout) != stream:
        raise AssertionError("v2 stream does not read back")
    return EncodeReport(rung, n, layout.stream_bytes, int(changed.shape[0]), int(one_to_two),
                        int((rho[changed] >= WET_COST).sum()))


def encode_v2(jpeg_in_path: str, jpeg_out_path: str, mode: str, type_tag: int, body: bytes,
              password: Optional[str] = None, max_rung: int = 5, rung: Optional[int] = None,
              seed: Optional[int] = None) -> EncodeReport:
    """Embed into an existing JPEG with J-UNIWARD costs (no side information).
    The smallest rung up to `max_rung` that fits is used unless `rung` is given."""
    im = jpeglib.read_dct(jpeg_in_path)
    planes = _component_planes(im)
    qts = [im.qt[im.quant_tbl_no[p]] for p in range(len(planes))]
    report = _embed(planes, qts, mode, type_tag, body, password, max_rung, rung, None,
                    np.random.default_rng(seed))
    im.write_dct(jpeg_out_path)
    return report


# Quantisation tables of UIImage.jpegData(compressionQuality: 0.85), natural
# order (docs/experiment-steganalysis.md §1; the D8 carrier quality).
Q85_LUMA = np.array([
    [1, 1, 1, 2, 3, 4, 6, 7], [1, 1, 1, 2, 3, 4, 6, 7], [1, 1, 2, 3, 4, 6, 7, 8],
    [2, 2, 3, 4, 6, 7, 8, 9], [3, 3, 4, 6, 7, 8, 9, 11], [4, 4, 6, 7, 8, 9, 11, 11],
    [6, 6, 7, 8, 9, 11, 11, 11], [7, 7, 8, 9, 11, 11, 11, 11]], dtype=np.uint16)
Q85_CHROMA = np.array(
    [[2, 2, 3, 5, 11, 11, 11, 11], [2, 3, 3, 8, 11, 11, 11, 11], [3, 3, 6, 11, 11, 11, 11, 11],
     [5, 8, 11, 11, 11, 11, 11, 11]] + [[11] * 8] * 4, dtype=np.uint16)


def quantise_rgb(rgb: np.ndarray, luma: np.ndarray = Q85_LUMA, chroma: np.ndarray = Q85_CHROMA):
    """Our own pixel -> coefficient step (the SI encoder needs u). RGB uint8,
    both sides multiples of 16. JFIF full-range YCbCr rounded to 8 bits,
    4:2:0 by the rounded 2x2 mean, level shift, orthonormal DCT, divide.
    Returns [(precover plane, u, c)] for Y, Cb, Cr."""
    from scipy.fft import dctn
    h, w = rgb.shape[:2]
    if h % 16 or w % 16:
        raise ValueError("the pixel encoder needs MCU-aligned (16 px) sizes")
    f = rgb.astype(np.float64)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    q8 = lambda x: np.clip(np.round(x), 0, 255)  # noqa: E731
    y = q8(0.299 * r + 0.587 * g + 0.114 * b)
    cb = q8(128 - 0.168736 * r - 0.331264 * g + 0.5 * b)
    cr = q8(128 + 0.5 * r - 0.418688 * g - 0.081312 * b)
    sub = lambda x: q8(x.reshape(x.shape[0] // 2, 2, x.shape[1] // 2, 2).mean(axis=(1, 3)))  # noqa: E731
    out = []
    for plane, qt in ((y, luma), (sub(cb), chroma), (sub(cr), chroma)):
        ph, pw = plane.shape
        blocks = (plane - 128).reshape(ph // 8, 8, pw // 8, 8).transpose(0, 2, 1, 3)
        u = dctn(blocks, axes=(2, 3), norm="ortho") / qt[None, None].astype(np.float64)
        out.append((plane.astype(np.uint8), u, np.rint(u).astype(np.int16)))
    return out


def encode_v2_from_pixels(rgb: np.ndarray, jpeg_out_path: str, mode: str, type_tag: int,
                          body: bytes, password: Optional[str] = None, max_rung: int = 5,
                          rung: Optional[int] = None, side_informed: bool = True,
                          seed: Optional[int] = None) -> EncodeReport:
    """Quantise the pixels ourselves at q0.85 and embed, with SI-UNIWARD costs
    when `side_informed` (the D6 encoder) or J-UNIWARD otherwise."""
    q = quantise_rgb(rgb)
    planes = [c.copy() for _, _, c in q]
    qts = [Q85_LUMA, Q85_CHROMA, Q85_CHROMA]
    side = [(pre, u) for pre, u, _ in q] if side_informed else None
    report = _embed(planes, qts, mode, type_tag, body, password, max_rung, rung, side,
                    np.random.default_rng(seed))
    im = jpeglib.from_dct(planes[0], planes[1], planes[2],
                          qt=np.stack([Q85_LUMA, Q85_CHROMA]), quant_tbl_no=[0, 1, 1])
    im.write_dct(jpeg_out_path)
    return report
