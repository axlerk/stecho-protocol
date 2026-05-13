# Test Vectors

JPEG carriers + expected `(mode, type_tag, body)` triples for Stecho v1.
The reference Python decoder verifies that an implementation written
from the spec alone recovers the same payload the encoder embedded.

## Layout

- `manifest.json` — index of vectors with mode, password, type, body (base64).
- `*.jpg`         — encoded carriers, one per vector.

## Status

The current batch is emitted by the **Python reference encoder**
([`../reference/python/generate_test_vectors.py`](../reference/python/generate_test_vectors.py)).
This is an interim arrangement until the Swift engine exists. Once the
Swift engine has a vector-emitting test, this manifest will be
regenerated from Swift and become the cross-implementation reference
that the Python decoder must read.

## Vectors

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

A passing run is evidence that the spec, the reference decoder, and
the encoder that produced these vectors are mutually consistent. When
the Swift engine starts emitting its own vectors, a passing run is
also evidence that the Swift binary on your phone does not encode
anything the spec does not describe.
