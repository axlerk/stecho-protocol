# Stecho Reference Decoder — Python

Independent re-implementation of Stecho v1 (`juniward-layer.md` +
`open-v1.md` + `stealth-v1.md`). ~600 LOC of Python, no Stecho Swift
source code touched at runtime.

For the normative spec see [`../..`](../..).

## Why this exists

If the spec is correct and the shipping Swift engine is correct, this
script reads any Stecho JPEG produced by the app — and the binary on
your phone has no way to deviate without the divergence being visible
here. That is the entire point of a reference implementation.

The Python encoder included in this module is **informational only**:
it exists so the spec can be self-tested without an iOS build. The
shipping Stecho app uses its own Swift implementation; the encoder side
is not part of the normative spec.

## Layout

| File | Purpose |
|------|---------|
| [`stc.py`](stc.py) | Self-contained STC encoder + decoder. Pinned to the canonical `h=10, w=12` Filler-Judas-Fridrich sub-matrix. |
| [`stecho_decode.py`](stecho_decode.py) | Position enumeration, J-UNIWARD cost map via `conseal`, PBKDF2 / HMAC permutation, AES-256-GCM, open / stealth mode framing, top-level `decode()`. |
| [`generate_test_vectors.py`](generate_test_vectors.py) | One-shot script that emits the initial test-vector batch via the Python encoder. |
| [`verify_test_vectors.py`](verify_test_vectors.py) | Runs the decoder against `../../test-vectors/manifest.json`. |
| [`requirements.txt`](requirements.txt) | `jpeglib`, `conseal`, `cryptography`, `Pillow`, `numpy`. |

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`jpeglib` wraps libjpeg-turbo and gives lossless access to quantized DCT
coefficients. `conseal` provides the J-UNIWARD cost map (verified by its
authors against the Binghamton MATLAB reference).

## Use

Decode a Stecho JPEG:

```bash
python stecho_decode.py path/to/photo.jpg                  # open mode only
python stecho_decode.py path/to/photo.jpg "your password"  # tries open, then stealth
```

Prints the decoded payload to stdout. Exits non-zero if no payload can
be recovered (which deliberately conflates "wrong password", "not a
Stecho photo", and "corrupted Stecho photo" — see spec).

## Verify against the committed test vectors

```bash
python verify_test_vectors.py ../../test-vectors
```

The current vectors are emitted by `generate_test_vectors.py`. Once the
Swift engine has a vector-emitting test, the manifest will be
regenerated from Swift output and this script becomes the
cross-implementation verifier.

## Regenerate vectors from Python (informational)

```bash
python generate_test_vectors.py ../../test-vectors
```

Salts and nonces are random per run, so the binary `.jpg` files differ
between runs. The manifest captures only what is decoder-deterministic
(password + expected `(mode, type, body)`); the JPEG content does not
need to match byte-for-byte across runs.

## Performance

The reference is built for clarity and correctness, not throughput. On
an Apple Silicon Mac, indicative numbers:

| Carrier   | Encode (open) | Encode (stealth) | Decode (stealth)  |
|-----------|---------------|-------------------|-------------------|
| 128×128   | ~0.6 s        | ~0.9 s           | ~0.4 s            |
| 256×256   | ~2 s          | ~3 s             | ~0.5 s            |
| 12 MP     | extrapolated  | extrapolated     | extrapolated      |
| (4032×3024)| ~5 min       | ~5 min           | ~10 s             |

The STC Viterbi forward pass is the bottleneck — the inner Python loop
has 1024 states per cover bit. For production work the Swift engine
will be 100-500× faster; the Python reference is calibrated for spec
verification on small-to-medium carriers, not bulk processing.

## Known limitations

- File I/O only: `jpeglib.read_dct` is path-based, so the decoder
  spills the input to a temp file on every call.
- Single-pass: no incremental / streaming API. The whole F4 stream is
  walked in memory.
- No timing-hardening: this is a spec reference, not a production
  decoder. PBKDF2 timing follows the `cryptography` library defaults;
  if you need constant-time guarantees for a hostile deployment, port
  to a vetted runtime.
- The encoder side bridges between J-UNIWARD's per-direction cost (±1)
  and STC's symmetric LSB-flip model by taking `min(rho_+1, rho_-1)`
  per coefficient. The "which direction to actually move" decision at
  apply time uses the F-family convention (decrement |c|), which is
  consistent with `JUNIWARD_ORIGINAL` symmetric mode.
