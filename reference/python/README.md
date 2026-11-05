# Stecho Reference Decoder — Python

Independent re-implementation of the Stecho wire formats: layer v2
(`juniward-layer.md` §V2 + `open-v2.md` + `stealth-v2.md`) and the frozen
layer v1 (`juniward-layer.md` §1–§9 + `open-v1.md` + `stealth-v1.md`).
No Stecho Swift source code touched at runtime.

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
| [`stc.py`](stc.py) | Self-contained STC encoder + decoder: v1's fixed `h=10, w=12` sub-matrix, and v2's variable block widths (`block_widths`, `stc_encode_v2`, `stc_decode_v2`). |
| [`stecho_v2.py`](stecho_v2.py) | Layer v2: non-zero cover, keyed permutation (open and stealth), rate ladder and its sub-matrices, per-plane J-UNIWARD and SI-UNIWARD costs, open-v2 / stealth-v2 encoder and decoder, a q0.85 pixel quantiser for SI. |
| [`stecho_decode.py`](stecho_decode.py) | Layer v1: position enumeration, J-UNIWARD cost map via `conseal`, PBKDF2 / HMAC permutation, AES-256-GCM, open / stealth mode framing. Top-level `decode()` / `decode_detailed()` for every version (open-v2, open-v1, stealth-v2, stealth-v1). |
| [`stc_submatrix_search.py`](stc_submatrix_search.py) | Seeded search that produced the v2 sub-matrices; [`stc_submatrix_search-result.json`](stc_submatrix_search-result.json) is its recorded output (`juniward-layer.md` §V2.6.3). |
| [`generate_test_vectors.py`](generate_test_vectors.py) | Emits the test vectors of one layer (`--layer v2`, the default, or `--layer v1`) and merges them into the manifest. |
| [`verify_test_vectors.py`](verify_test_vectors.py) | Runs the decoder against `../../test-vectors/manifest.json`: mode, layer, rung, type and body, plus wrong-password checks for stealth vectors. |
| [`requirements.txt`](requirements.txt) | `jpeglib`, `conseal`, `cryptography`, `Pillow`, `numpy`, `scipy`. Decoding needs only `jpeglib`, `numpy`, `cryptography`; `conseal` and `scipy` are for the encoder's costs. |

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
python stecho_decode.py path/to/photo.jpg                  # open mode only (v2, then v1)
python stecho_decode.py path/to/photo.jpg "your password"  # then stealth (v2, then v1)
```

Prints the decoded payload to stdout and the mode, layer and (v2) rung to
stderr. Exits non-zero if no payload can
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
python generate_test_vectors.py ../../test-vectors              # layer v2
python generate_test_vectors.py ../../test-vectors --layer v1   # layer v1
```

Each run rewrites only the layer it is asked for. Salts, nonces, padding
and the J-UNIWARD change directions are random per run, so the binary `.jpg` files differ
between runs. The manifest captures only what is decoder-deterministic
(password + expected `(mode, type, body)`); the JPEG content does not
need to match byte-for-byte across runs.

## Re-run the v2 sub-matrix search (informational)

```bash
python stc_submatrix_search.py --n 20480 --out result.json
python stc_submatrix_search.py --n 20480 --validate
```

Seeded (numpy `default_rng`, seed 20261104, one generator per rung), so a
re-run with numpy 2.5.4 prints the table of `juniward-layer.md` §V2.6.3;
the recorded run is `stc_submatrix_search-result.json`. Checked
2026-11-04 for rungs 4 and 5 (`--rungs 4,5`): same columns and the same
scores to four decimals. Rungs 1–3 were not re-run. A few minutes of one
core.

## Performance

v2, 256×256 carriers (about 33 000 non-zero AC coefficients): an encode
takes about 0.5 s (STC search over 2^10 states per cover element, about
10 µs per element in numpy), a stealth decode about 0.5 s, mostly
PBKDF2 (measured 2026-11-04 on an M1 Pro under shared load, so rough).

v1, on an Apple Silicon Mac, indicative numbers:

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
- v1 encoder only: the encoder side bridges between J-UNIWARD's per-direction cost (±1)
  and STC's symmetric LSB-flip model by taking `min(rho_+1, rho_-1)`
  per coefficient. The "which direction to actually move" decision at
  apply time uses the F-family convention (decrement |c|), which is
  consistent with `JUNIWARD_ORIGINAL` symmetric mode. The v2 encoder
  instead computes the symmetric cost per plane and chooses the direction
  per `juniward-layer.md` §V2.9.4.
- v2's STC encoder keeps one bit per step and trellis state
  (`n × 128` bytes): fine for test carriers, not for 12 MP photos.
