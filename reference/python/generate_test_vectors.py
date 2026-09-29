#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""Generate the initial batch of Stecho v1 test vectors.

Run once; commit the outputs. When the Swift engine has a vector-emitting
test, this script's outputs become the interim baseline until the Swift
output replaces it.

Usage:
    python generate_test_vectors.py ../../test-vectors
"""

import base64
import json
import secrets
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from stecho_decode import (
    encode_open,
    encode_stealth,
    TYPE_TEXT,
    TYPE_AUDIO_OPUS,
)


def make_carrier(size: int, path: Path, seed: int) -> None:
    """Deterministic carrier: diagonal gradient + reproducible noise."""
    rng = np.random.default_rng(seed)
    yy, xx = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
    base = ((xx + yy) % 256).astype(np.int16)
    noise = rng.integers(-30, 31, size=(size, size), dtype=np.int16)
    arr = np.clip(
        np.stack([base, base, base], axis=-1) + noise[..., None],
        0, 255,
    ).astype(np.uint8)
    Image.fromarray(arr, "RGB").save(path, quality=85)


def main(out_dir: str) -> int:
    base = Path(out_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)

    audio_rng = np.random.default_rng(7777)
    fake_audio = bytes(audio_rng.integers(0, 256, size=200, dtype=np.uint8))

    plan = [
        {
            "name": "open-text-hello-ascii",
            "carrier_size": 256, "carrier_seed": 1,
            "mode": "open", "password": None,
            "type": "text", "type_tag": TYPE_TEXT,
            "body": b"hello world",
            "notes": "Smallest open-mode vector: tiny ASCII payload.",
        },
        {
            "name": "open-empty",
            "carrier_size": 256, "carrier_seed": 2,
            "mode": "open", "password": None,
            "type": "text", "type_tag": TYPE_TEXT,
            "body": b"",
            "notes": "Zero-length open-mode payload — header only, all padding.",
        },
        {
            "name": "stealth-text-hello-ascii",
            "carrier_size": 256, "carrier_seed": 3,
            "mode": "stealth", "password": "correct horse battery staple",
            "type": "text", "type_tag": TYPE_TEXT,
            "body": b"hello world",
            "notes": "Smallest stealth-mode vector.",
        },
        {
            "name": "stealth-text-unicode",
            "carrier_size": 256, "carrier_seed": 4,
            "mode": "stealth", "password": "пар0ль",
            "type": "text", "type_tag": TYPE_TEXT,
            "body": "Привет, Stecho! 👋".encode("utf-8"),
            "notes": "UTF-8 body with Cyrillic + emoji and a non-ASCII password.",
        },
        {
            "name": "stealth-audio-binary",
            "carrier_size": 256, "carrier_seed": 5,
            "mode": "stealth", "password": "voice-test",
            "type": "audio", "type_tag": TYPE_AUDIO_OPUS,
            "body": fake_audio,
            "notes": "200 bytes of pseudo-random bytes labeled as audio — stands in for real Opus.",
        },
    ]

    vectors_json = []
    for entry in plan:
        carrier_path = base / f"_carrier-{entry['name']}.jpg"
        jpeg_path = base / f"{entry['name']}.jpg"
        make_carrier(entry["carrier_size"], carrier_path, entry["carrier_seed"])
        if entry["mode"] == "open":
            encode_open(str(carrier_path), entry["type_tag"], entry["body"], str(jpeg_path))
        else:
            encode_stealth(
                str(carrier_path), entry["password"],
                entry["type_tag"], entry["body"], str(jpeg_path),
            )
        carrier_path.unlink()
        vectors_json.append({
            "name": entry["name"],
            "jpeg": jpeg_path.name,
            "carrier_size": f"{entry['carrier_size']}x{entry['carrier_size']} synthetic",
            "mode": entry["mode"],
            "password": entry["password"],
            "type": entry["type"],
            "body_base64": base64.b64encode(entry["body"]).decode("ascii"),
            "notes": entry["notes"],
        })
        print(f"  emitted {jpeg_path.name} ({jpeg_path.stat().st_size} B)")

    manifest = {
        "generator": "spec/reference/python/generate_test_vectors.py",
        "spec_version": "juniward-layer + open-v1 + stealth-v1",
        "notes": (
            "Initial vectors emitted by the Python reference encoder. The "
            "shipping Swift engine will re-emit equivalent vectors from its "
            "own test suite once available. The Python decoder must read "
            "vectors from either source."
        ),
        "vectors": vectors_json,
    }
    (base / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  wrote manifest.json ({len(vectors_json)} vectors)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: generate_test_vectors.py <out-dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
