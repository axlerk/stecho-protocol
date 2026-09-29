#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Pavel Khudiakov
"""Verify the Python reference decoder against the committed test vectors.

Usage:
    python verify_test_vectors.py ../../test-vectors

Reads `manifest.json`, runs `stecho_decode.decode` on each carrier JPEG with
the listed mode + password, and compares the produced (mode, type, body)
against the expected values. A passing run is evidence the Python decoder
matches the spec end-to-end.

Once the Swift engine emits vectors, the same script verifies that the
Python decoder reads the Swift output bit-for-bit — i.e. cross-implementation
agreement, the "no backdoor" property.
"""

import base64
import json
import sys
from pathlib import Path

from stecho_decode import decode, TYPE_TEXT, TYPE_AUDIO_OPUS

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

        jpeg_bytes = jpeg_path.read_bytes()
        got = decode(jpeg_bytes, password)
        if got is None:
            print(f"  [FAIL] {name}: decode returned None")
            failures += 1
            continue
        got_mode, got_type, got_body = got
        if got_mode != expected_mode:
            print(f"  [FAIL] {name}: mode={got_mode!r} != expected {expected_mode!r}")
            failures += 1
            continue
        if got_type != expected_type:
            print(f"  [FAIL] {name}: type 0x{got_type:02x} != expected 0x{expected_type:02x}")
            failures += 1
            continue
        if got_body != expected_body:
            print(f"  [FAIL] {name}: body mismatch ({len(got_body)} B vs {len(expected_body)} B)")
            failures += 1
            continue
        print(f"  [ OK ] {name} (mode={got_mode}, {len(got_body)} B body)")

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
