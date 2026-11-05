#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""Verify the Python reference decoder against the committed test vectors.

Usage:
    python verify_test_vectors.py ../../test-vectors

Reads `manifest.json`, runs the top-level `stecho_decode.decode_detailed` on
each carrier JPEG with the listed password, and compares the produced mode,
layer (v1 / v2), rung (v2) and (type, body) against the expected values.
For every stealth vector it also checks that the carrier yields nothing
without the password and with a wrong one. A passing run is evidence the
Python decoder matches the spec end-to-end.

Once the Swift engine emits vectors, the same script verifies that the
Python decoder reads the Swift output bit-for-bit — i.e. cross-implementation
agreement, the "no backdoor" property.
"""

import base64
import json
import sys
from pathlib import Path

from stecho_decode import decode_detailed, TYPE_TEXT, TYPE_AUDIO_OPUS

TYPE_NAMES = {"text": TYPE_TEXT, "audio": TYPE_AUDIO_OPUS}


def main(vectors_dir: str) -> int:
    base = Path(vectors_dir).resolve()
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: no manifest at {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text())
    vectors = manifest.get("vectors", [])
    if not vectors:
        print("WARNING: manifest contains no vectors", file=sys.stderr)
        return 0

    failures = 0
    for v in vectors:
        name = v["name"]
        jpeg_path = base / v["jpeg"]
        expected_mode = v["mode"]
        password = v.get("password")
        expected_type_str = v["type"]
        expected_body = base64.b64decode(v["body_base64"])

        if expected_type_str not in TYPE_NAMES:
            print(f"  [skip] {name}: unknown manifest type '{expected_type_str}'")
            continue
        expected_type = TYPE_NAMES[expected_type_str]

        expected_layer = v.get("layer", "v1")
        expected_rung = v.get("rung")

        jpeg_bytes = jpeg_path.read_bytes()
        got = decode_detailed(jpeg_bytes, password)
        if got is None:
            print(f"  [FAIL] {name}: decode returned None")
            failures += 1
            continue
        problems = []
        if got["mode"] != expected_mode:
            problems.append(f"mode={got['mode']!r} != expected {expected_mode!r}")
        if got["layer"] != expected_layer:
            problems.append(f"layer={got['layer']!r} != expected {expected_layer!r}")
        if expected_rung is not None and got["rung"] != expected_rung:
            problems.append(f"rung={got['rung']} != expected {expected_rung}")
        if got["type_tag"] != expected_type:
            problems.append(f"type 0x{got['type_tag']:02x} != expected 0x{expected_type:02x}")
        if got["body"] != expected_body:
            problems.append(f"body mismatch ({len(got['body'])} B vs {len(expected_body)} B)")
        if expected_mode == "stealth":
            if decode_detailed(jpeg_bytes, None) is not None:
                problems.append("decodes without the password")
            if decode_detailed(jpeg_bytes, password + "x") is not None:
                problems.append("decodes with a wrong password")
        if problems:
            print(f"  [FAIL] {name}: " + "; ".join(problems))
            failures += 1
            continue
        rung = f", rung {got['rung']}" if got["rung"] is not None else ""
        print(f"  [ OK ] {name} (mode={got['mode']}, layer={got['layer']}{rung}, "
              f"{len(got['body'])} B body)")

    if failures:
        print(f"\n{failures} vector(s) failed.", file=sys.stderr)
        return 1
    print(f"\nAll {len(vectors)} vector(s) passed.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: verify_test_vectors.py <test-vectors-dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
