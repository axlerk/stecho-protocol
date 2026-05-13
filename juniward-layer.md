# JUNIWARD Embedding Layer

Both Stecho modes (`open-v1`, `stealth-v1`) share the same way of mapping
a flat message bit stream to AC DCT coefficient LSB modifications. This
document defines that mapping.

The wire-format details that **differ** between modes (permutation,
framing, AES wrapper) live in the mode-specific specs. This document
covers only what they share: the position list, the J-UNIWARD distortion
function, and the STC matrix-coding embedding.

> **Notation.** All multi-byte integer fields are little-endian unless
> stated otherwise. `||` is byte-string concatenation. `[a..b]` is a
> half-open byte slice (`b` exclusive). `LSB(x)` means `|x| & 1`. `bpac`
> stands for "bits per non-zero AC coefficient".

## 1. Inputs

- `jpeg` — a baseline or progressive JPEG carrier. The decoder MUST be
  able to parse it into quantized DCT coefficients without performing
  inverse DCT (i.e. the coefficients themselves must be accessible).
- `π` — a permutation of `[0, N)` over the canonical AC position list
  (§2). Supplied by the calling mode (`open-v1` uses a fixed
  permutation; `stealth-v1` derives it from the password).
- `message_bits` — bit stream to embed. For modes with framing on top
  of this layer (e.g. AES headers), `message_bits` already includes
  those bytes serialized to bits MSB-first.

## 2. Position enumeration

Let `S` be the JPEG's quantized spectral data, modelled as a list of
component planes in JPEG component declaration order. Each plane `p`
has block grid `units.y × units.x`. Each block has 63 AC coefficients
addressed by JPEG zigzag index `z ∈ {1, …, 63}` (index 0 is DC and is
not used).

The canonical AC position list is built in this order:

```
positions = []
for p in planes (in JPEG component declaration order):
    for y in 0 .. units.y - 1:
        for x in 0 .. units.x - 1:
            for z in 1 .. 63:
                positions.append((p, y, x, z))
```

Let `N = len(positions)`. Both encoder and decoder enumerate identically.

> The list contains *all* AC slots, including positions whose current
> coefficient is zero. This matters for capacity bookkeeping below.

## 3. J-UNIWARD distortion

For each AC coefficient position, compute the embedding cost
`ρ(p, by, bx, z)` using J-UNIWARD as defined in:

> Holub, V., Fridrich, J., & Denemark, T. (2014).
> **Universal distortion function for steganography in an arbitrary
> domain.** EURASIP Journal on Information Security, 2014(1), 1.
> DOI: [10.1186/1687-417X-2014-1](https://doi.org/10.1186/1687-417X-2014-1)

Stecho v1 freezes the following parameter choices:

| | |
|---|---|
| Stabilization constant `σ` | `2⁻⁶ = 0.015625` (matches `conseal.juniward._costmap.compute_cost` default and the original DDE/Binghamton MATLAB reference) |
| Wavelet | Daubechies-8 (`db8`) directional filters |
| Decomposition scales | 3 (LL is discarded; LH, HL, HH retained at each scale) |
| Cost symmetry | Symmetric: `ρ⁺ = ρ⁻` (the original 2014 formulation) |
| Wet-cost (unembeddable) | `10¹³` for DC, zero-valued AC, and saturated pixel positions |

### 3.1 Reference implementation

The Stecho reference decoder uses
[`conseal.juniward.compute_cost_adjusted`](https://conseal.readthedocs.io/)
with `implementation = Implementation.JUNIWARD_ORIGINAL` as the canonical
cost-map source. `conseal` 2025.11 was verified by its authors against
the published Binghamton MATLAB reference.

Independent implementations of this spec MUST produce cost maps that
agree with the `conseal` output to within `1e-6` relative tolerance on
the test vectors shipped under `spec/test-vectors/`. Disagreements
indicate either a numerical-precision issue (acceptable if below
tolerance) or an algorithmic divergence (a bug in either implementation).

> **Why we don't re-derive the math here.** J-UNIWARD has 30+ pages of
> derivation in the source paper and existing reference implementations
> in MATLAB, C++, Python, and Rust. Re-stating it here would either
> duplicate that work or introduce subtle bugs through paraphrase.
> Following the RFC pattern (e.g. RFC 8439 referencing ChaCha20 from
> RFC 7539), Stecho v1 names the algorithm and fixes its parameters.

## 4. STC matrix coding

Embedding chooses which AC LSBs to flip via Syndrome-Trellis Codes (STC):

> Filler, T., Judas, J., & Fridrich, J. (2011).
> **Minimizing Additive Distortion in Steganography Using Syndrome-Trellis
> Codes.** IEEE Transactions on Information Forensics and Security,
> 6(3), 920–935.
> DOI: [10.1109/TIFS.2011.2134094](https://doi.org/10.1109/TIFS.2011.2134094)

STC takes (cover LSBs, distortion costs, message bits) and produces
(modified LSBs) that simultaneously:

- have minimum total distortion (sum of costs of flipped bits), and
- satisfy a parity-check matrix equation `H · x_stego = m` where `m` is
  the message bit vector.

The decoder recovers `m` by a single linear pass: `m = H · x_stego mod 2`
applied to the LSBs read in permuted order. No backward-tracking or
optimisation needed on the decode side.

### 4.1 Parameters

Stecho v1 freezes:

| | |
|---|---|
| Constraint height `h`     | `10` (1024 trellis states) |
| Sub-matrix `Ĥ` width `w`  | `12` — gives exact embedding rate `1/12 ≈ 0.0833` ≈ the target `α = 0.08` from open / stealth mode specs |
| Sub-matrix `Ĥ` columns    | `[581, 831, 659, 877, 781, 929, 1003, 1021, 655, 729, 983, 611]` — 12 values, each a 10-bit column read bit-`i` = `(col >> i) & 1` for row `i ∈ {0..9}` |
| LSB definition            | `LSB(c) = \|c\| & 1` (sign-independent) |

The 12 column values are taken from the canonical sub-matrix table
embedded in the Binghamton STC reference implementation
(`ml_stc_linux_make_v1.0/ml_stc_src/common.cpp`, accessible at
[dde.binghamton.edu/download/syndrome](http://dde.binghamton.edu/download/syndrome/)).
That table operationalises the `h ∈ 7..12, w ∈ 2..20` "good" sub-matrices
published in Filler-Judas-Fridrich 2011. The Filler-Fridrich Binghamton
table is the de-facto industry reference for STC parameters in
academic and applied steganography. Stecho v1 pins exactly the
`h = 10, w = 12` row.

`h = 10` is chosen over the simpler `h = 7` or `h = 8` because at our
embedding rates (~0.08 bpac) the coding-loss difference between
`h = 10` and lower values is the main distinguisher of
approach-to-the-rate-distortion-bound. Speed cost of `h = 10` is
roughly 4× over `h = 8` (256 → 1024 trellis states), still sub-second
on Apple Silicon for 100 KB payloads.

### 4.2 Coding rate

The fixed sub-matrix width `w = 12` (§4.1) directly pins the embedding
rate at `α = 1/w = 1/12 ≈ 0.0833` bpac. The encoder MUST NOT vary `α`;
the decoder MUST assume `α = 1/12`.

The full parity-check matrix `H` is constructed from `Ĥ` by staggered
diagonal repetition per Filler-Judas-Fridrich 2011 §III: the sub-matrix
slides one row at a time, contributing `w = 12` columns of cover bits
per row of `H`. For `n` cover bits, the resulting `H` is
`m × n` where `m = n / 12` (rounded; padding handled per the cited
section).

Stecho modes **pad** the message bit stream to exactly `floor(α × N)`
bits regardless of payload size (see `open-v1.md` and `stealth-v1.md`
for the per-mode padding strategy). This means every Stecho JPEG of a
given carrier `N` embeds the same number of message bits, so the
encoded statistical profile depends only on the carrier — never on the
payload length. There is no rate-level length oracle.

### 4.3 Wet positions

A position is **wet** (`ρ = WET_COST`) and MUST NOT be modified if any of:

- coefficient is DC (`z = 0` — never reached by §2's enumeration)
- coefficient is zero
- block has any saturated pixel after decompression (J-UNIWARD's
  `avoid_saturated` flag in `conseal`)

The STC encoder handles wet positions via the wet-cost mechanism: their
contribution to total distortion is `10¹³`, so the Viterbi search
overwhelmingly avoids modifying them.

> **Why zeros are wet.** F5-style modification of zero-AC coefficients
> (introducing a `±1`) would create coefficients whose absence in the
> cover is a strong statistical signature. J-UNIWARD avoids this by
> design.

## 5. Encoding (informative)

The encoder is implementation detail and not normative. A correct STC
encoder must produce `x_stego` satisfying `H · x_stego = m` with minimum
total `ρ` over flipped positions, where:

```
x_cover[i] = LSB(coef at positions[π[i]])    for i in 0..n-1
ρ[i]       = cost at positions[π[i]]         for i in 0..n-1
H          = parity-check matrix from sub-matrix Ĥ
m          = message bit vector
```

Standard STC encoding uses Viterbi forward-pass + traceback over a
trellis with `2^h` states. Reference C++ implementation is in the
Binghamton STC toolbox (`http://dde.binghamton.edu/download/syndrome/`).
The Python reference decoder ships a Python port of this algorithm,
verified against the C++ output on a corpus of fixed
`(cover, costs, message)` triples.

## 6. Decoding (normative)

Given a modified JPEG, the permutation `π`, the expected message length
`m`, and the STC sub-matrix `Ĥ` (frozen by v1), recover the message bits:

```
1. Parse the JPEG into spectral coefficients.
2. Build positions[] per §2.
3. Read x_stego[i] = LSB(coef at positions[π[i]]) for i in 0..n-1.
   Wet positions still contribute their LSB; they simply weren't
   modified by the encoder. The decoder treats them no differently.
4. Construct H of dimensions m × n from Ĥ per Filler-Judas-Fridrich §III.
5. Compute message = (H · x_stego) mod 2.
6. Return message as bit stream.
```

Steps 4 and 5 are pure linear algebra over GF(2): no Viterbi, no cost
computation, no permutation back-and-forth. This is the asymmetric
property of STC that makes the decoder dramatically simpler than the
encoder.

## 7. Capacity

Stecho v1 fixes `α = 1/12 ≈ 0.0833` via the frozen sub-matrix width
`w = 12` (§4.1). Capacity is therefore a deterministic function of the
carrier:

```
embedded_bits = floor(N / 12)
embedded_bytes = embedded_bits / 8 (rounding to byte boundary)
```

Anything beyond — alternate `w`, adaptive rate, multi-rate
constructions — is out of v1 scope and would require a new layer spec
version.

In bytes:

```
practical_capacity_bytes = floor(α_target × N / 8) - mode_overhead
```

where `N` is the position count from §2 and `mode_overhead` is the
fixed header size of the calling mode (`open-v1`: see that spec;
`stealth-v1`: see that spec).

> Typical numbers for a 12 MP iPhone JPEG at Q=0.85 (N ≈ 14M):
> - α = 0.05 → ~87 KB payload budget (~55s of 12 kbps Opus voice)
> - α = 0.08 → ~140 KB payload budget (~87s of voice) — **v1 default**
> - α = 0.10 → ~175 KB payload budget (~110s of voice)
> - α = 0.15 → ~263 KB payload budget — past the recommended ceiling
>
> A 1 MP carrier (N ≈ 1.2M) at α = 0.08 gives ~12 KB — text messages
> and very short voice.
>
> A 24 MP carrier (iPhone 15 Pro default, N ≈ 28M) at α = 0.08 gives
> ~280 KB — comfortable for 2+ minutes of voice.
>
> These ranges drive the camera-side "traffic light" UX and the
> Photos-picked-carrier capacity countdown, both mandatory product
> invariants per `AGENTS.md`.

## 8. Threat model summary (informative)

A full threat model lives in [`THREAT_MODEL.md`](THREAT_MODEL.md).
This section restates only what J-UNIWARD + STC give us at this layer.

**Defended:**

- **Content-adaptive embedding.** Modifications concentrate in textured /
  high-frequency regions where the cost is low, avoiding smooth /
  predictable regions. Resists detectors that key on uniform-region
  histogram perturbations (e.g. classical chi-squared, calibration).
- **Minimum-distortion property.** STC produces the lowest-total-cost
  embedding for the given message and matrix dimensions. No simpler
  encoding (greedy, F4, F5) hides as well at the same payload rate.

**Not defended:**

- **Modern CNN-class steganalysis.** SOTA detectors (SRNet, GBRAS-Net,
  Yedroudj-Net) trained on J-UNIWARD-modified JPEGs at moderate-to-high
  embedding rates (α ≥ 0.1) detect with accuracy 75-90% on standard
  test corpora (BOSSbase, ALASKA II). At Stecho's v1 default (α = 0.08)
  accuracy is ~70-78%, dropping to ~65% at α = 0.05 — meaningful but
  not zero. Real-world detection on iPhone-photo carriers (24 MP color)
  is likely lower than these academic numbers because the carrier
  distribution is far from BOSSbase, but this gap is not formally
  measured by Stecho.
- **Side-channel leakage from message length.** §4.2 above notes the
  length is declared in mode headers, which is a small length-oracle
  leak the calling mode may or may not protect against.
- **Transport-layer recompression.** This layer assumes the JPEG
  reaches the recipient with quantized DCT coefficients preserved
  byte-for-byte. iMessage attachment recompression behaviour is
  observation-level, not security-guarantee — see
  [`THREAT_MODEL.md`](THREAT_MODEL.md) §4.3 for the threat-model
  statement of this failure mode.

## 9. Glossary

| Term            | Definition                                                       |
|-----------------|------------------------------------------------------------------|
| AC coefficient  | A non-DC entry in a JPEG block's DCT spectrum (zigzag index 1–63) |
| bpac            | Bits per non-zero AC coefficient (embedding rate metric)         |
| Daubechies-8    | The 8-tap orthogonal wavelet `db8`, used by J-UNIWARD residuals |
| J-UNIWARD       | JPEG Universal Wavelet Relative Distortion (Holub-Fridrich 2014) |
| permutation `π` | A bijection of `[0, N)` over the canonical AC list, mode-supplied |
| STC             | Syndrome-Trellis Codes (Filler-Judas-Fridrich 2011)             |
| sub-matrix `Ĥ`  | The small bit-vector pattern that, when staggered, builds the full parity-check matrix `H` |
| wet cost        | Distortion `10¹³` flagging an unembeddable coefficient           |
