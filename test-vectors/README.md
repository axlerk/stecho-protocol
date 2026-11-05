# Test Vectors

JPEG carriers + expected `(mode, type_tag, body)` triples for Stecho
layer v1 and layer v2.
The reference Python decoder verifies that an implementation written
from the spec alone recovers the same payload the encoder embedded.

## Layout

- `manifest.json` — index of vectors with layer (`v1` / `v2`), mode,
  password, type, body (base64). v2 entries also give the rung the
  decoder must find, the cover size `cover_n` (non-zero AC count), the
  stream size `stream_bytes`, the cost function the encoder used and the
  number of coefficients it changed — for debugging another decoder.
- `*.jpg`         — encoded carriers, one per vector (`v2-*` for layer v2).

## Status

The current batch is emitted by the **Python reference encoder**
([`../reference/python/generate_test_vectors.py`](../reference/python/generate_test_vectors.py)).
This is an interim arrangement until the Swift engine exists. Once the
Swift engine has a vector-emitting test, this manifest will be
regenerated from Swift and become the cross-implementation reference
that the Python decoder must read.

## Vectors

### Layer v1 (frozen)

| Name                          | Mode    | Type  | Body                          |
|-------------------------------|---------|-------|-------------------------------|
| `open-text-hello-ascii`       | open    | text  | `"hello world"`               |
| `open-empty`                  | open    | text  | `""`                          |
| `stealth-text-hello-ascii`    | stealth | text  | `"hello world"`               |
| `stealth-text-unicode`        | stealth | text  | `"Привет, Stecho! 👋"`        |
| `stealth-audio-binary`        | stealth | audio | 200 bytes of pseudo-random    |

Carriers are synthetic 256×256 gradient + reproducible-seed noise
JPEGs. Real-world iPhone photo carriers will produce larger n and
correspondingly higher capacity — these vectors only test the wire
format, not capacity behavior.

### Layer v2

Emitted 2026-11-04 by `generate_test_vectors.py` (default `--layer v2`).
They cover both modes, all five rungs, text and audio, J-UNIWARD and
SI-UNIWARD carriers, a grayscale carrier, a carrier with partial MCUs, an
empty body, and a message deliberately placed above the smallest rung that
fits.

| Name | Mode | Rung | Type | Body | Carrier | Costs |
|---|---|---|---|---|---|---|
| `v2-open-text-hello` | open | 1 | text | 11 B text | 256x256 synthetic, PIL q85 | J-UNIWARD |
| `v2-open-empty` | open | 1 | text | 0 B text | 256x256 synthetic, PIL q85 | J-UNIWARD |
| `v2-open-text-rung3` | open | 3 | text | 318 B text | 256x256 synthetic, PIL q85 | J-UNIWARD |
| `v2-open-audio-rung5` | open | 5 | audio | 1500 B pseudo-random | 256x256 synthetic, PIL q85 | J-UNIWARD |
| `v2-open-text-si-rung4` | open | 4 | text | 1026 B text | 256x256 synthetic, reference quantiser, UIImage q0.85 tables | SI-UNIWARD |
| `v2-open-gray-rung2` | open | 2 | text | 124 B text | 256x256 synthetic grayscale, PIL q85 | J-UNIWARD |
| `v2-open-odd-size` | open | 1 | text | 42 B text | 250x170 synthetic, PIL q85 | J-UNIWARD |
| `v2-stealth-text-hello` | stealth | 1 | text | 11 B text | 256x256 synthetic, PIL q85 | J-UNIWARD |
| `v2-stealth-text-unicode-rung2` | stealth | 2 | text | 120 B text | 256x256 synthetic, PIL q85 | J-UNIWARD |
| `v2-stealth-text-forced-rung3` | stealth | 3 | text | 23 B text | 256x256 synthetic, PIL q85 | J-UNIWARD |
| `v2-stealth-audio-rung4` | stealth | 4 | audio | 600 B pseudo-random | 256x256 synthetic, PIL q85 | J-UNIWARD |
| `v2-stealth-audio-si-rung5` | stealth | 5 | audio | 2000 B pseudo-random | 256x256 synthetic, reference quantiser, UIImage q0.85 tables | SI-UNIWARD |

Carriers are synthetic: per-channel gradients with seeded noise and one
small saturated patch (so saturated blocks exist). "PIL q85" carriers are
written by Pillow and embedded with J-UNIWARD; the SI carriers are
quantised by the reference itself with the `UIImage.jpegData(0.85)`
tables and embedded with SI-UNIWARD. Audio bodies are pseudo-random bytes
labelled `audio`, not real Opus (the Opus container is outside the spec,
layer O5).

The Swift test copy in `StechoTests/Fixtures/` still holds only the v1
set. When the Swift v2 engine lands, copy the `v2-*` files and the
manifest there; until it decodes v2, `CrossImplVectorsTests` should skip
entries whose `layer` is not `v1`.

## Why vectors are committed as binary

Each stealth vector embeds a freshly-random AES salt and nonce
(`stealth-v1.md` §4), and the open-mode padding is random too. The
JPEG bytes therefore differ across runs even for the same
`(carrier, password, body)` triple. The committed `.jpg` is the
artifact; the manifest captures only what is decoder-deterministic
(password + expected plaintext).

This makes the vectors **immutable** once committed — they are not
regenerated on every build. They are only refreshed when the wire
format changes (in which case the spec gets a new version anyway).

## Verify

**Python decoder** (spec authority):

```bash
cd ../reference/python
pip install -r requirements.txt
python verify_test_vectors.py ../../test-vectors
```

**Swift decoder** (the shipping engine):

```bash
xcodebuild test -project ../../Stecho.xcodeproj -scheme Stecho \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -only-testing:StechoTests/CrossImplVectorsTests
```

The Swift test reads its fixtures from `StechoTests/Fixtures/` — a
**copy** of this directory's `.jpg` files plus `manifest.json`, kept
in the test bundle's synced-resources folder because Xcode's
`fileSystemSynchronizedGroups` cannot pull in files from outside the
target's folder. **When the vectors here are regenerated, update both
copies** (this dir → `StechoTests/Fixtures/`). The dual location is
documented at the top of `StechoTests/CrossImplVectorsTests.swift`.

The verifier also checks that every stealth vector yields nothing
without its password and with a wrong one.

A passing run is evidence that the spec, the reference decoder, and
the encoder that produced these vectors are mutually consistent. When
the Swift engine starts emitting its own vectors, a passing run is
also evidence that the Swift binary on your phone does not encode
anything the spec does not describe.
