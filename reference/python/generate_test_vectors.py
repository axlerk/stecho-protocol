#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""Generate Stecho test vectors with the Python reference encoder.

Vectors are committed and immutable: each run draws fresh salts, nonces and
padding, so the JPEG bytes differ between runs. Regenerate only when the
wire format changes. A run rewrites the v2 JPEGs and the manifest.

Layer v1 (retired 2026-11-10, no shipping build reads it) has no generator
any more and no vectors in the manifest.

Usage:
    python generate_test_vectors.py ../../test-vectors

Carriers are synthetic (gradients plus seeded noise), never photos.
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from stecho_decode import TYPE_AUDIO_OPUS, TYPE_TEXT

TYPE_NAMES = {TYPE_TEXT: "text", TYPE_AUDIO_OPUS: "audio"}


# ---------------------------------------------------------------------------
# v2
# ---------------------------------------------------------------------------

def make_pixels_v2(width: int, height: int, seed: int, gray: bool = False) -> np.ndarray:
    """v2 carrier pixels: per-channel gradients in [40, 215] plus seeded
    texture noise, with one small saturated patch (white and black squares)
    so the saturated-block wet rule is exercised."""
    rng = np.random.default_rng(seed)
    yy, xx = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
    chans = []
    for k in range(1 if gray else 3):
        g = 40 + 175 * ((xx * (k + 1) + yy * (3 - k)) % 256) / 255.0
        n = rng.normal(0, 14, size=(height, width))
        chans.append(g + n)
    arr = np.clip(np.stack(chans, axis=-1), 0, 255)
    arr[8:24, 8:24] = 255
    arr[8:24, 24:40] = 0
    arr = np.round(arr).astype(np.uint8)
    return arr[..., 0] if gray else arr


def pseudo_audio(size: int, seed: int) -> bytes:
    return bytes(np.random.default_rng(seed).integers(0, 256, size=size, dtype=np.uint8))


TEXT_RU = ("Это проверочный текст для Stecho v2: он длиннее короткой записки, "
           "чтобы занять следующую ступень. ")
TEXT_EN = ("Stecho v2 test text. It is long enough to need a higher rung than a "
           "one-line note, and it is plain ASCII. ")


def v2_plan() -> list:
    # (name, (w, h), seed, gray, source, mode, password, type, body, forced rung,
    #  expected rung, notes). source "jpeg" = PIL q85 carrier, J-UNIWARD costs;
    # "pixels" = our own q0.85 quantiser, SI-UNIWARD costs.
    unicode_body = ("Привет, Stecho v2! 👋 " * 4).encode("utf-8")
    return [
        ("v2-open-text-hello", (256, 256), 11, False, "jpeg", "open", None, TYPE_TEXT,
         b"hello world", None, 1, "Smallest open-v2 vector, rung 1."),
        ("v2-open-empty", (256, 256), 12, False, "jpeg", "open", None, TYPE_TEXT,
         b"", None, 1, "Zero-length open-v2 body: header and padding only."),
        ("v2-open-text-rung3", (256, 256), 13, False, "jpeg", "open", None, TYPE_TEXT,
         (TEXT_EN * 3).encode("ascii"), None, 3, "ASCII text that needs rung 3."),
        ("v2-open-audio-rung5", (256, 256), 14, False, "jpeg", "open", None, TYPE_AUDIO_OPUS,
         pseudo_audio(1500, 14), None, 5,
         "1500 pseudo-random bytes labelled audio at the top rung (0.4)."),
        ("v2-open-text-si-rung4", (256, 256), 15, False, "pixels", "open", None, TYPE_TEXT,
         (TEXT_RU * 6).encode("utf-8"), None, 4,
         "UTF-8 text, rung 4, carrier quantised by the reference at q0.85 with "
         "SI-UNIWARD costs: the decoder is the same as for J-UNIWARD carriers."),
        ("v2-open-gray-rung2", (256, 256), 16, True, "jpeg", "open", None, TYPE_TEXT,
         (TEXT_EN * 1).encode("ascii") + b"Grayscale carrier.", None, 2,
         "One-component (grayscale) carrier."),
        ("v2-open-odd-size", (250, 170), 17, False, "jpeg", "open", None, TYPE_TEXT,
         b"250x170: partial MCUs, chroma 16x11 blocks", None, 1,
         "Carrier whose size is not a multiple of the 16 px MCU: the cover counts each "
         "component's own blocks (ceil(size / 8)), not MCU padding."),
        ("v2-stealth-text-hello", (256, 256), 21, False, "jpeg", "stealth",
         "correct horse battery staple", TYPE_TEXT, b"hello world", None, 1,
         "Smallest stealth-v2 vector, rung 1."),
        ("v2-stealth-text-unicode-rung2", (256, 256), 22, False, "jpeg", "stealth",
         "пар0ль", TYPE_TEXT, unicode_body, None, 2,
         "UTF-8 body with Cyrillic and emoji, non-ASCII password, rung 2."),
        ("v2-stealth-text-forced-rung3", (256, 256), 23, False, "jpeg", "stealth",
         "rung-three", TYPE_TEXT, b"short text, higher rung", 3, 3,
         "Short text placed at rung 3 although rung 1 fits (a preset may do this): "
         "the decoder must not assume the smallest rung."),
        ("v2-stealth-audio-rung4", (256, 256), 24, False, "jpeg", "stealth",
         "voice-test", TYPE_AUDIO_OPUS, pseudo_audio(600, 24), None, 4,
         "600 pseudo-random bytes labelled audio, rung 4 (0.2, the Balanced ceiling)."),
        ("v2-stealth-audio-si-rung5", (256, 256), 25, False, "pixels", "stealth",
         "voice-test", TYPE_AUDIO_OPUS, pseudo_audio(2000, 25), None, 5,
         "2000 pseudo-random bytes labelled audio at rung 5, SI-UNIWARD carrier."),
    ]


def v2_vectors(base: Path) -> list:
    from stecho_v2 import encode_v2, encode_v2_from_pixels

    out = []
    for (name, (w, h), seed, gray, source, mode, password, type_tag, body, forced,
         expect, notes) in v2_plan():
        jpeg_path = base / f"{name}.jpg"
        px = make_pixels_v2(w, h, seed, gray)
        if source == "jpeg":
            carrier_path = base / f"_carrier-{name}.jpg"
            Image.fromarray(px, "L" if gray else "RGB").save(carrier_path, quality=85)
            rep = encode_v2(str(carrier_path), str(jpeg_path), mode, type_tag, body,
                            password=password, rung=forced, seed=seed)
            carrier_path.unlink()
            cost, carrier = "J-UNIWARD", "PIL q85"
        else:
            rep = encode_v2_from_pixels(px, str(jpeg_path), mode, type_tag, body,
                                        password=password, rung=forced, seed=seed)
            cost, carrier = "SI-UNIWARD", "reference quantiser, UIImage q0.85 tables"
        if rep.rung != expect:
            raise SystemExit(f"{name}: landed on rung {rep.rung}, plan says {expect}")
        out.append({
            "name": name, "layer": "v2", "jpeg": jpeg_path.name,
            "carrier_size": f"{w}x{h} synthetic{' grayscale' if gray else ''}, {carrier}",
            "mode": mode, "password": password, "type": TYPE_NAMES[type_tag],
            "rung": rep.rung, "cover_n": rep.n, "stream_bytes": rep.stream_bytes,
            "cost": cost, "changes": rep.changes,
            "body_base64": base64.b64encode(body).decode("ascii"), "notes": notes,
        })
        print(f"  emitted {jpeg_path.name} ({jpeg_path.stat().st_size} B): rung {rep.rung}, "
              f"n {rep.n}, stream {rep.stream_bytes} B, {rep.changes} changes "
              f"({rep.one_to_two} of them 1->2, {rep.wet_changes} wet)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    a = ap.parse_args()
    base = Path(a.out_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    manifest_path = base / "manifest.json"
    vectors = v2_vectors(base)
    manifest = {
        "generator": "spec/reference/python/generate_test_vectors.py",
        "spec_version": "juniward-layer (v2) + open-v2 + stealth-v2",
        "notes": (
            "Vectors emitted by the Python reference encoder, all layer v2. Layer v1 "
            "was retired on 2026-11-10 and its vectors were removed. "
            "The Python decoder must read vectors from any conforming encoder."
        ),
        "vectors": vectors,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(f"  wrote manifest.json ({len(vectors)} vectors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
