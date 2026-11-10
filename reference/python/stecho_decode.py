# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""
Reference decoder entry point for the Stecho wire format: the top-level
`decode()` / `decode_detailed()` that dispatch open-v2 and stealth-v2
(`stealth-v2.md` §8), the protocol constants and the helpers `stecho_v2.py`
shares (the JPEG zigzag table, the PBKDF2 keys, the bit/byte conversions).

Layer v1 (`open-v1.md`, `stealth-v1.md`) is retired and not read: it was
written by one TestFlight build only, never released, and no shipping build
decodes it since 2026-11-10 (`../../README.md`, "Retired: layer v1"). A v1
carrier decodes to None here, like any JPEG without a payload.

This module is the canonical, independent re-implementation of Stecho's
JPEG steganography. It uses:

- `jpeglib` for lossless DCT coefficient access (in `stecho_v2.py`).
- `cryptography` for AES-256-GCM and PBKDF2-HMAC-SHA256.

The encoder side lives in `stecho_v2.py` and is informational: it exists so
the spec can be self-tested without an iOS build. The shipping Stecho app
uses its own Swift implementation; the encoder side is not part of the
normative spec.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# ---------------------------------------------------------------------------
# Protocol constants — see ../../juniward-layer.md, ../../open-v2.md,
# ../../stealth-v2.md
# ---------------------------------------------------------------------------

# Permutation key of stealth-v2 (stealth-v2.md §2.1). The "v1" in the salt is
# a label stealth-v2 inherited, not a leftover of the retired layer.
STEALTH_PERM_PBKDF2_SALT = b"stecho-stealth-v1-perm-salt"   # 27 bytes
PBKDF2_ITER              = 600_000
KEY_LEN                  = 32                                # AES-256

# Open framing magic (open-v2.md §4)
OPEN_MAGIC               = b"SECO"                           # 4 bytes

# Stealth framing (stealth-v2.md §6)
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



# ---------------------------------------------------------------------------
# Permutation key — see stealth-v2.md §2.1
# ---------------------------------------------------------------------------

def _stealth_perm_key(password: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=KEY_LEN,
        salt=STEALTH_PERM_PBKDF2_SALT,
        iterations=PBKDF2_ITER,
    )
    return kdf.derive(password)


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
# Stealth-v2 AES key — see stealth-v2.md §5
# ---------------------------------------------------------------------------

def _aes_key_from(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=KEY_LEN,
        salt=salt,
        iterations=PBKDF2_ITER,
    )
    return kdf.derive(password)


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

def decode_detailed(jpeg_bytes: bytes, password: Optional[str] = None) -> Optional[dict]:
    """Top-level dispatch (stealth-v2.md §8): open-v2, then, with a password,
    stealth-v2. Returns a dict with mode, layer ("v2"), rung, type_tag and
    body, or None. Layer-v1 carriers return None (retired, not read)."""
    import stecho_v2   # local import: stecho_v2 imports this module

    res = stecho_v2.decode_open_v2(jpeg_bytes)
    if res is not None:
        return dict(mode="open", layer="v2", rung=res[0], type_tag=res[1], body=res[2])
    if password is None:
        return None
    res = stecho_v2.decode_stealth_v2(jpeg_bytes, password)
    if res is not None:
        return dict(mode="stealth", layer="v2", rung=res[0], type_tag=res[1], body=res[2])
    return None


def decode(jpeg_bytes: bytes, password: Optional[str] = None) -> Optional[Tuple[str, int, bytes]]:
    """Returns (mode, type_tag, body) or None; see `decode_detailed`."""
    res = decode_detailed(jpeg_bytes, password)
    if res is None:
        return None
    return res["mode"], res["type_tag"], res["body"]


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
    result = decode_detailed(data, pw)
    if result is None:
        print("No Stecho payload.", file=sys.stderr)
        sys.exit(1)
    mode, type_tag, body = result["mode"], result["type_tag"], result["body"]
    print(f"mode={mode} layer={result['layer']} rung={result['rung']} type=0x{type_tag:02x} "
          f"body_len={len(body)}", file=sys.stderr)
    if type_tag == TYPE_TEXT:
        sys.stdout.write(body.decode("utf-8", errors="replace"))
    else:
        sys.stdout.buffer.write(body)
