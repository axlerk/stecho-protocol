# JUNIWARD Embedding Layer

The embedding layer maps a flat message byte stream to changes of quantised
AC DCT coefficients of a JPEG, using J-UNIWARD content-adaptive costs and
Syndrome-Trellis Codes (STC). The mode specs put a frame on top of it
(magic and length in open mode, AES-GCM in stealth mode).

This document defines two versions of the layer:

| Layer | Status | Modes on top | Sections |
|---|---|---|---|
| **v2** | current; draft until the items under "Open" close | [`open-v2.md`](open-v2.md), [`stealth-v2.md`](stealth-v2.md) | §V2.1–§V2.13 |
| **v1** | retired 2026-11-10, historical; not read by any shipping or reference decoder | [`open-v1.md`](open-v1.md), [`stealth-v1.md`](stealth-v1.md) | §1–§9 |

v1 keeps its original section numbers because code, tests and other
documents cite them. The two versions are not compatible: a v1 decoder
reads garbage from a v2 carrier and the reverse. v1 was written by one
TestFlight build only and is not decoded any more (see "Layer v1 (retired)"
below); the dispatch order of a v2 decoder is in
[`stealth-v2.md`](stealth-v2.md) §8. Open-mode streams carry a version byte (`0x01` for v1, `0x02` for
v2); stealth streams have no plaintext marker in either version and are
told apart by which one authenticates.

What v2 changes, and why, is argued in
[`../docs/proposal-layer-v2.md`](../docs/proposal-layer-v2.md) (owner
decisions D1–D9 of 2026-11-04 in its §8) and measured in
[`../docs/experiment-steganalysis-v2-sim.md`](../docs/experiment-steganalysis-v2-sim.md).
In short: v1 fills the whole stream on every carrier at `1/12` bit per AC
slot (zeros included) and is easy to detect; v2 embeds only into non-zero
coefficients, never creates or removes a zero, and uses the smallest of
five rates that fits the message.

> **Notation.** All multi-byte integer fields are little-endian unless
> stated otherwise. `||` is byte-string concatenation. `[a..b]` is a
> half-open byte slice (`b` exclusive). `LSB(x)` means `|x| & 1`.
> `floor`, `ceil` are on exact rationals (implementations use integer
> arithmetic). bpnzAC: bits per non-zero AC coefficient of the cover.

## Open (as of 2026-11-04)

These are undecided. The text below is written with the current proposal
and each place that depends on an open item says so. Items O1, O3, O4 and
O8 change the wire format if they change; the others do not.

| # | Item | Current text | Why open |
|---|---|---|---|
| O1 | **Rate ladder** (proposal D4) | Five rungs `1/40, 1/20, 1/10, 1/5, 2/5` (§V2.5) | D4 lists five rungs as the candidate, not as adopted. Fewer rungs leak less and decode faster; more waste less capacity. |
| O2 | **Preset ceilings** (D1) | Hidden 0.1 / Balanced 0.2 (default) / Long messages 0.4; free one rung lower (§V2.5.3) | Adopted for now; final values follow a CNN detector and real-encoder carriers (proposal §7). Encoder policy only, unless a ceiling above 0.4 is wanted (that needs a new rung). |
| O3 | **Stealth: one PBKDF2 per rung tried** | Framing as proposal §3.6: the per-message AES salt is inside each rung's stream, so every rung a decoder tries costs one PBKDF2-600k for the AES key ([`stealth-v2.md`](stealth-v2.md) §9) | The proposal (§3.2) says "PBKDF2 for stealth runs once, not per try"; that does not hold for this framing. A wrong password costs 1 + 5 PBKDF2 runs and 5 STC passes. Alternatives (a once-per-password key with HKDF per message, or a rung-independent header) change the stealth framing and its brute-force cost; owner's decision. |
| O4 | **STC sub-matrices** | Own seeded search, h = 10 (§V2.6.3) | The Binghamton table v1 used stops at width 20 and is not available here beyond v1's w = 12 row. At w = 12 the published matrix scored 0.5 % lower distortion than the best of 16 random candidates, so a longer search or a published table could be slightly more efficient. |
| O5 | **Audio body format** (type `0x02`) | Not defined by these specs (§V2.1) | The body is the app's Opus container (`StechoCore/OpusCodec.swift`, container version 1, 20 ms frames, one `u16` length per frame). Another session is measuring a change of the frame length; that changes the body, not this layer. The container is not yet specified for independent decoders. |
| O6 | **J-UNIWARD variant** | conseal `JUNIWARD_ORIGINAL`, as the Swift engine (§V2.9) | The v2 simulation measured conseal's default `JUNIWARD_FIX_OFF_BY_ONE`. Encoder-only; the difference in detectability is not measured. |
| O7 | **v1 in the app** | Closed 2026-11-10: v1 is retired, no decoder reads it | The proposal said v2 replaces v1 with no dual decoder. v1 had been written by one TestFlight build only; the app and the reference dropped the v1 fallback and its vectors. |
| O8 | **Stealth permutation key** | v2 reuses v1's PBKDF2 salt, new keystream info tag ([`stealth-v2.md`](stealth-v2.md) §2) | A choice of this draft: one PBKDF2 run gives the permutation key (it was shared with v1's fallback until v1 was retired). Needs review. |
| O9 | **Detectability figures** | Simulated only (§V2.12) | No STC, no CNN in the simulation; final numbers come from proposal §7 and go into `THREAT_MODEL.md`. |

---

# Layer v2

## V2.1 Inputs and outputs

Encoder:

- `jpeg` — a baseline or progressive JPEG carrier, or pixels that the
  encoder quantises itself (needed for SI-UNIWARD, §V2.9.3).
- `perm` — the keyed permutation of the mode (§V2.4).
- `stream` — the framed message of the mode, `L_k` bytes for the chosen
  rung `k` (§V2.5). The mode pads its frame to exactly `L_k` bytes.

Decoder:

- `jpeg` — the received JPEG. Its quantised coefficients MUST be readable
  without an inverse DCT.
- `perm` — the keyed permutation of the mode.
- Output: for each rung `k = 1..5`, the `L_k`-byte stream of that rung.
  The mode decides which rung, if any, holds a valid frame.

The bodies the modes carry (text, Opus audio) are opaque to the layer.

## V2.2 Coefficient planes

A JPEG has one quantised coefficient plane per component, in component
declaration order (Y, Cb, Cr for the carriers Stecho writes; one plane for
grayscale; all components otherwise). Component `i` has a block grid of

```
blocks_y(i) = ceil(ceil(Y × V_i / V_max) / 8)
blocks_x(i) = ceil(ceil(X × H_i / H_max) / 8)
```

blocks (ITU-T T.81 §A.1.1: `X × Y` the image size, `H_i, V_i` the
component's sampling factors). These are the component's own blocks.
**Blocks that an interleaved scan codes only to complete a partial MCU
are not part of the plane.** Example, read with jpeglib 1.0.2 (libjpeg) on
a 250×170 4:2:0 JPEG written by Pillow: Y is 22×32 blocks, Cb and Cr 11×16
each (test vector `v2-open-odd-size`).

Stecho's own encoder resamples carriers to MCU multiples (16 px for 4:2:0),
so its carriers have no partial MCUs; the rule above still holds for any
JPEG.

Each block has 63 AC coefficients at zigzag indices `z = 1..63` (`z = 0`
is DC and never used).

## V2.3 Cover

The **cover** is the list of non-zero AC coefficients in canonical order:

```
cover = []
for p in planes (declaration order):
    for by in 0 .. blocks_y(p) - 1:
        for bx in 0 .. blocks_x(p) - 1:
            for z in 1 .. 63:
                if coef(p, by, bx, z) != 0:
                    cover.append((p, by, bx, z))
n = len(cover)
```

The order is v1's position order (§2) with the zeros left out. The bit an
element carries is `LSB(c) = |c| & 1`.

Because a valid v2 carrier never changes a zero into a non-zero or the
reverse (§V2.7), the decoder enumerates exactly the same `n` elements, in
the same order, from the stego JPEG as the encoder did from the cover.

## V2.4 Permutation

Both modes walk the cover in a keyed pseudo-random order. The construction
is v1's stealth permutation with the key and info tag as parameters:

```
keystream(key, info, L) = HMAC-SHA256(key, BE32(0) || info)
                       || HMAC-SHA256(key, BE32(1) || info)
                       || ... truncated to L bytes
BE32(c) = c as 4-byte big-endian

ks = keystream(key, info, 4 × n)
idx = [0, 1, ..., n - 1]
for i = n - 1 down to 1:
    j = uint32_be(ks[4i .. 4i + 4]) mod (i + 1)
    swap idx[i], idx[j]
perm = idx
```

Step `s` of the walk visits `cover[perm[s]]`. The key and info tag come
from the mode:

| Mode | `key` | `info` |
|---|---|---|
| open-v2 | `SHA-256(ASCII "stecho-open-v2-perm-key")` = `cfd8f182773909afb32cbdf6e85d7b060540b01e5d9ea2d82a02654d5ce1f369` | ASCII `"stecho-open-v2-perm"` |
| stealth-v2 | the password-derived permutation key of [`stealth-v2.md`](stealth-v2.md) §2 | ASCII `"stecho-stealth-v2-perm"` |

The open-mode key is public: the permutation only spreads the cover
elements evenly over the code (in v1 open mode, without a permutation,
13–17 % of the changes on camera photos were forced into zeros,
`docs/experiment-r1-engine-budget.md`). The modulo has a bias below
`n / 2³²`, as in v1; it is part of the definition.

The permutation depends on `n` only, not on the rung: one permutation
serves all rung trials.

## V2.5 Rate ladder

### V2.5.1 Rungs

The layer embeds at one of five rates, the **rungs**. Rung `k` carries
`q_k / d_k` message bits per cover element:

| Rung `k` | rate `q_k / d_k` | bpnzAC | sub-matrix width `W_k = ceil(d_k / q_k)` |
|---|---|---|---|
| 1 | 1/40 | 0.025 | 40 |
| 2 | 1/20 | 0.05 | 20 |
| 3 | 1/10 | 0.1 | 10 |
| 4 | 1/5 | 0.2 | 5 |
| 5 | 2/5 | 0.4 | 3 |

(O1: the ladder is the proposal's candidate.)

For a cover of `n` elements, rung `k` has:

```
L_k   = floor(n × q_k / (8 × d_k))         # stream bytes
m_k   = 8 × L_k                             # message bits
w(j)  = floor((j + 1) × d_k / q_k) - floor(j × d_k / q_k),   j = 0 .. m_k - 1
n_k   = Σ w(j) = floor(m_k × d_k / q_k)     # cover elements used, n_k ≤ n
```

Message bit `j` owns a block of `w(j)` consecutive elements of the
permuted walk; block `j` starts at walk step `floor(j × d_k / q_k)`. For
`q_k = 1` every block has width `d_k`; for rung 5 the widths alternate
`2, 3, 2, 3, …`. Walk steps `n_k .. n - 1` belong to no block at that
rung and carry nothing.

A rung with `L_k` smaller than the mode's fixed overhead (10 bytes in open
mode, 49 in stealth mode) is unusable on that carrier; encoders do not
pick it and decoders skip it.

### V2.5.2 Rung choice and trial

- The encoder picks a rung whose payload capacity (mode spec) holds the
  message, and pads the frame to `L_k`. It SHOULD pick the smallest such
  rung up to the ceiling its policy allows (§V2.5.3). A higher rung is
  valid: decoders MUST NOT assume the smallest.
- The rung is not written anywhere. The decoder computes the stream of
  each usable rung, **in ascending order `k = 1, 2, …, 5`**, and hands
  each to the mode; the first rung whose frame the mode accepts is the
  result. (The chance that a wrong rung also validates is about 2⁻⁴⁰ in
  open mode, magic and version, and 2⁻¹²⁸ in stealth mode, the GCM tag;
  the order makes the outcome deterministic even then.)

### V2.5.3 Presets (informative, encoder policy)

The presets of proposal §5.1 cap the rung a message may use; they are not
in the wire format, and a carrier from any preset opens on any decoder.

| Preset | ceiling | Pro: highest rung | Free: highest rung ("half the photo") |
|---|---|---|---|
| Hidden | 0.1 | 3 | 2 |
| **Balanced** (default) | 0.2 | 4 | 3 |
| Long messages | 0.4 | 5 | 4 |

Free is half the capacity (D5), which on this ladder is one rung down.

## V2.6 STC

### V2.6.1 Code

Embedding uses Syndrome-Trellis Codes:

> Filler, T., Judas, J., & Fridrich, J. (2011).
> **Minimizing Additive Distortion in Steganography Using Syndrome-Trellis
> Codes.** IEEE Transactions on Information Forensics and Security,
> 6(3), 920–935.
> DOI: [10.1109/TIFS.2011.2134094](https://doi.org/10.1109/TIFS.2011.2134094)

Constraint height `h = 10` at every rung. Rung `k` has one sub-matrix
`Ĥ_k` of `W_k` columns; a column is a 10-bit integer whose bit `r`
(`(col >> r) & 1`) is row `r`.

### V2.6.2 Parity-check matrix (normative)

`H_k` has `m_k` rows and `n_k` columns. Walk step `i` lies in block
`j(i)` at column `c(i) = i − floor(j(i) × d_k / q_k)` inside the block,
and its column of `H_k` is

```
H_k[j(i) + r, i] = (Ĥ_k[c(i)] >> r) & 1     for r = 0 .. 9 with j(i) + r < m_k
H_k[row, i]      = 0                         for every other row
```

That is the staggered construction of Filler–Judas–Fridrich with the
rows past `m_k` cut off, and with block `j` using the first `w(j)` columns
of `Ĥ_k`. The message is

```
message_bits = H_k · x  (mod 2),   x[i] = LSB(cover[perm[i]]),  i = 0 .. n_k - 1
```

### V2.6.3 Sub-matrices (normative values)

```
Ĥ_1 (rung 1, 40 columns):
    795,  549,  989,  725, 1021,  535,  995,  843,  779,  777,
    615,  649,  729,  745,  841,  651,  905,  659,  981,  737,
    719,  701,  675,  661, 1003,  623,  787,  965,  991,  929,
    537,  917,  681,  913,  643,  705,  889,  671, 1013,  803
Ĥ_2 (rung 2, 20 columns):
    745,  795,  779,  835,  805,  523,  889,  921,  589,  521,
    617,  569,  839,  767,  533,  575,  703,  989,  959,  535
Ĥ_3 (rung 3, 10 columns):
    973,  827,  981,  813,  519,  741,  689,  887,  529,  603
Ĥ_4 (rung 4, 5 columns):
    675,  985,  613,  917,  795
Ĥ_5 (rung 5, 3 columns; width-2 blocks use the first two):
    535,  981,  883
```

Provenance (informative; O4). The values come from
[`reference/python/stc_submatrix_search.py`](reference/python/stc_submatrix_search.py),
seed `20261104`, run 2026-11-04 with numpy 2.5.4; the full output is
[`reference/python/stc_submatrix_search-result.json`](reference/python/stc_submatrix_search-result.json).
Per rung: 48 random candidates (distinct columns with bits 0 and 9 set,
like every column of v1's matrix), each scored as the mean distortion of
the STC encoder over 3 trials of 20 480 cover elements with costs uniform
on (0, 1], divided by the rate-distortion bound (optimal embedding
simulator) for the same costs and payload; the best 6 re-scored on 12
fresh trials; the lowest kept.

| Rung | width | distortion / bound, kept matrix (12 trials) | stage 1 over 48 candidates: best / median / worst |
|---|---|---|---|
| 1 | 40 | 1.1654 | 1.1433 / 1.1708 / 1.2038 |
| 2 | 20 | 1.1541 | 1.1508 / 1.1778 / 1.2012 |
| 3 | 10 | 1.1547 | 1.1429 / 1.1585 / 1.1729 |
| 4 | 5 | 1.1384 | 1.1333 / 1.1482 / 1.1705 |
| 5 | 3 | 1.1108 | 1.1042 / 1.1224 / 1.1725 |

Check of the scoring (same script, `--validate`): at `w = 12`, v1's
published matrix scored 1.1496 against 1.1553 / 1.1613 / 1.1725
(best / median / worst) for 16 random candidates on the same 12 trials;
none beat it. The scoring therefore ranks a published matrix first, and
the gap to a random search is about half a percent of distortion.

## V2.7 Valid v2 carrier (normative)

A JPEG is a valid v2 carrier of `stream` at rung `k` under `perm` if,
relative to the cover JPEG it was made from:

1. **The zero set is unchanged:** every coefficient (DC and AC, every
   plane) that is zero in the cover is zero in the stego, and every
   non-zero one is non-zero. Hence the cover of §V2.3 is the same list.
2. **Only cover elements change, by one step in magnitude, keeping the
   sign:** `|c'| = |c| ± 1`, `sign(c') = sign(c)`. A `|c| = 1` that changes
   becomes `|c| = 2`. `|c'|` stays within what the JPEG can code
   (1023 for 8-bit sample precision). DC coefficients, the quantisation
   tables, the sampling factors and the image size are unchanged.
3. **The syndrome holds:** `H_k · x' = bits(stream)` (§V2.6.2), with the
   stream read MSB-first: byte `t` bit `7 − b` is message bit `8t + b`.

Rules 1 and 3 are what a decoder relies on; rule 2 is what the security
of the layer relies on. How the stego is re-serialised (Huffman tables,
progressive or baseline, segment layout) is not part of the format;
container fingerprints are out of scope here (proposal F5).

## V2.8 Decoding (normative)

```
fn layer_v2_streams(jpeg, perm_for_n, min_bytes) -> list of (k, stream):
    planes = parse_jpeg_coefficients(jpeg)            # §V2.2
    cover  = nonzero_ac_in_canonical_order(planes)   # §V2.3
    n      = len(cover)
    perm   = perm_for_n(n)                           # §V2.4, mode's key
    x      = [LSB(cover[perm[i]]) for i in 0 .. n - 1]
    out = []
    for k in 1 .. 5:
        L = floor(n × q_k / (8 × d_k))
        if L < min_bytes: continue
        m = 8 × L
        bits = [0] × m
        for i in 0 .. n_k - 1:                       # n_k = floor(m × d_k / q_k)
            if x[i] == 1:
                j = block of i;  c = column of i     # §V2.5.1
                for r in 0 .. 9:
                    if j + r < m and (Ĥ_k[c] >> r) & 1:
                        bits[j + r] ^= 1
        out.append((k, bits_to_bytes_msb_first(bits)))
    return out
```

The mode tries the streams in the order returned and stops at the first
valid frame. A decoder may compute the streams lazily, one rung at a time.
No costs, no Viterbi search and no knowledge of SI or the preset are needed
to decode.

## V2.9 Costs and encoding (informative)

Costs decide which cover elements an encoder changes. They are not part of
the wire format: any cost map gives a carrier that decodes. They are what
makes the carrier hard to detect, so a conforming Stecho encoder uses one
of the two below.

### V2.9.1 J-UNIWARD per plane

> Holub, V., Fridrich, J., & Denemark, T. (2014).
> **Universal distortion function for steganography in an arbitrary
> domain.** EURASIP Journal on Information Security, 2014(1), 1.
> DOI: [10.1186/1687-417X-2014-1](https://doi.org/10.1186/1687-417X-2014-1)

Parameters as in v1 (§3): `σ = 2⁻⁶`, Daubechies-8 directional filters,
3 levels, symmetric cost `ρ⁺ = ρ⁻`. The reference uses conseal 2026.11,
`compute_cost` with `JUNIWARD_ORIGINAL` (O6).

**New in v2:** each component's cost is computed on **that component's
own decompressed plane**: dequantise its coefficients with its own table,
orthonormal 8×8 inverse DCT, add 128, round and clip to `[0, 255]`, at the
component's own resolution (`8 × blocks_y` by `8 × blocks_x`, chroma
subsampled). v1 used a luma stand-in `Y[::2, ::2]` for chroma, which also
made carriers with an odd number of luma block rows or columns unencodable
(proposal F4).

### V2.9.2 Wet elements

A cover element gets the cost `10¹³` (it is still in the cover, and STC may
change it only if nothing else satisfies the syndrome) if its block's
decompressed plane has a pixel equal to 0 or 255. Zeros are not wet in v2:
they are not in the cover at all.

### V2.9.3 SI-UNIWARD (encoder option, adopted D6)

When the encoder quantises the pixels itself it knows each coefficient's
unquantised value `u` (`c = round(u)`, rounding error `e = u − c`). It may
then use side-informed costs:

- `ρ_SI = (1 − 2|e|) × ρ`, with `ρ` the J-UNIWARD cost computed on the
  precover (the 8-bit plane before the DCT), and the change moves `c`
  toward `u`.
- If moving toward `u` would turn `|c| = 1` into 0, the change must go to
  `|c| = 2` instead and costs the unscaled `ρ`. If `e = 0` the cost is `ρ`
  and the direction free.
- At modes `(row, col) = (0, 4), (4, 0), (4, 4)` an element with
  `|e| = 1/2` is wet: integer pixels put those modes on a 1/8 grid, so exact
  halves are common there and would cost nothing (the SI-UNIWARD paper's
  rule, as recalled by the v2 simulation; not re-checked here).

SI-UNIWARD changes only which elements change and in which direction. The
carrier still meets §V2.7 and decodes like any other: test vectors
`v2-open-text-si-rung4` and `v2-stealth-audio-si-rung5` are SI carriers.

### V2.9.4 Direction

STC decides which elements flip their LSB; the encoder then chooses the
direction: `|c| = 1` always grows to 2; at `|c| = 1023` it shrinks; with
SI it moves toward `u` (above); with J-UNIWARD, whose cost is symmetric,
the reference draws the direction at random (the v2 simulation did the
same). Always shrinking `|c|` would bias the histogram the way F5-class
embedding does.

### V2.9.5 Encoder outline

```
fn layer_v2_encode(jpeg_or_pixels, perm_for_n, stream, k):
    planes, side_info = coefficients (and u, precover if SI)
    cover = nonzero_ac_in_canonical_order(planes); n = len(cover)
    perm  = perm_for_n(n)
    ρ, dir = costs and directions per cover element      # §V2.9.1-4
    x     = [LSB(cover[perm[i]]) for i in 0 .. n_k - 1]
    y     = STC_embed(x, ρ[perm[0 .. n_k - 1]], bits(stream), Ĥ_k, widths)
    for i where y[i] != x[i]:
        e = cover[perm[i]]; c = coef(e)
        coef(e) = sign(c) × (|c| + dir(e))
    write the JPEG with the same tables
```

`STC_embed` is the Viterbi search of Filler–Judas–Fridrich over `2^h`
states with the block widths of §V2.5.1, keeping the cheapest final
state (rows past `m_k` are cut off, so every final state is valid). The
reference ([`reference/python/stc.py`](reference/python/stc.py),
`stc_encode_v2`) keeps one bit per step and state, `n_k × 128` bytes; a
phone encoder needs the checkpointed traceback of §4.1.

## V2.10 Capacity (informative)

Capacity is `L_k` minus the mode's overhead (10 bytes open, 49 stealth),
so it depends on the photo's texture and size through `n`, not on its
pixel count alone. Using the class medians of non-zero AC counts measured
in the v2 simulation (q0.85, our own encoder;
`docs/experiment-steganalysis-v2-sim.md` §1) and Opus at 1600 B/s
(12 kbps) or 850 B/s (6 kbps), stealth mode:

| Carrier (median `n`) | rung 3 (0.1) | rung 4 (0.2) | rung 5 (0.4) |
|---|---|---|---|
| real photo, 2048 px (1 155 724) | 14 446 B: 9.0 s / 16.9 s | 28 893 B: 18.0 s / 33.9 s | 57 786 B: 36.1 s / 67.9 s |
| real photo, 3024 px (2 154 939) | 26 936 B: 16.8 s / 31.6 s | 53 873 B: 33.6 s / 63.3 s | 107 746 B: 67.3 s / 126.7 s |
| wallpaper, 2048 px (644 011) | 8 050 B: 5.0 s / 9.4 s | 16 100 B: 10.0 s / 18.9 s | 32 200 B: 20.1 s / 37.8 s |

The real-photo medians are over 5 scenes (50 crops); they are an
illustration, not a guarantee. An encoder MUST compute `n` from the actual
carrier and refuse a message that does not fit its ceiling rung
(`AGENTS.md`: capacity gating is mandatory).

## V2.11 Decode cost (informative)

Per carrier: one coefficient parse, one cover enumeration, one permutation
per mode (`4n` keystream bytes and a Fisher–Yates pass), then per rung tried
one linear STC pass over `n_k ≤ n` elements. A carrier with no payload in a
mode costs all five passes of that mode. For v1, R1 measured whole decodes
of 0.06 s (open) to 0.6 s (stealth, PBKDF2 included) at 2048×1536 on phones
(proposal §3.2). A v2 pass runs over the non-zero count, about a quarter of
v1's all-slot count on real photos (simulation §1: 0.249), so it should be
cheaper (inferred, not measured). Stealth adds PBKDF2 work per rung ([`stealth-v2.md`](stealth-v2.md)
§9, O3).

## V2.12 Threat model summary (informative)

Full threat model: [`THREAT_MODEL.md`](THREAT_MODEL.md) (not yet
updated for v2; proposal work item 6).

What v2 changes at this layer:

- **The change rate follows the message**, in five steps. A text note
  lands on rung 1 and carries a sixteenth of the bits of a rung-5 voice
  note; it also changes far fewer coefficients (simulated, SI, real
  photos: 0.015 changes per non-zero AC at 0.05 bpnzAC against 0.136 at
  0.4). The price is a size leak: anyone who can read
  the stream (open mode, or stealth with the password) learns the rung,
  i.e. the message size to within 2×; an observer without the password
  can estimate the rate only statistically.
- **No zeros are created or removed** and zeros are not in the cover, the
  change v1 forced on sparse carriers.
- **Detectability, simulated:** on real photos at q0.85 with SI-UNIWARD,
  every detector in the v2 simulation scored AUC ≤ 0.583 at 0.2 bpnzAC,
  and the untrained `beta_Y` test 0.929 at 0.4
  (`docs/experiment-steganalysis-v2-sim.md`; optimal simulator instead of
  STC, no CNN). Smooth images are more detectable at the same rate. These
  are not measurements of carriers from this encoder (O9).

Not defended, as in v1: a CNN-class detector trained on our carriers is
not yet measured and may do much better than the simulated detectors;
transport recompression destroys the payload (`THREAT_MODEL.md` §4.3).

## V2.13 Glossary (v2 additions)

| Term | Definition |
|---|---|
| bpnzAC | Bits per non-zero AC coefficient of the cover: v2's rate unit |
| cover (v2) | The non-zero AC coefficients of all planes, in canonical order (§V2.3) |
| `n` | Number of cover elements |
| rung `k` | One of the five rates `q_k / d_k` of §V2.5 |
| `L_k` | Stream bytes at rung `k`: `floor(n × q_k / (8 × d_k))` |
| block width `w(j)` | Cover elements owned by message bit `j` at a rung |
| `Ĥ_k` | The sub-matrix of rung `k` (§V2.6.3) |
| SI-UNIWARD | Side-informed J-UNIWARD: costs scaled by the rounding error; encoder only |
| wet | Cost `10¹³`: an element STC changes only when nothing else satisfies the syndrome |

---

# Layer v1 (retired, historical)

> **Retired (2026-11-10).** Layer v1 was written by exactly one TestFlight
> build (build 1) and never reached a release. No shipping decoder and no
> reference decoder reads it; a v1 carrier reads as "no hidden data". The
> sections below are kept unchanged as history because v2 cites their
> numbers and reuses the permutation-key derivation (§V2.4,
> [`stealth-v2.md`](stealth-v2.md) §2.1). See [`README.md`](README.md),
> "Retired: layer v1".

The sections below are layer v1 as it was frozen, with their original numbers.
**Errata of 2026-11-04** (wire format unchanged; the text now matches the
reference decoder, the Swift engine and the committed v1 vectors): v1's
rate is `1/12` bit per AC *slot*, zeros included, not `α = 0.08` per
non-zero AC coefficient, and the stream is `floor(floor(N / 12) / 8)`
bytes for `N` AC slots (proposal finding F6).

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
roughly 4× over `h = 8` (256 → 1024 trellis states). Because open-v1
and stealth-v1 always fill the whole stream, the Viterbi search visits
`1024 × n` states for a carrier with `n` AC positions, whatever the
payload size (informative, measured 2026-10-31 with the Swift encoder,
search only: 2048×1536 / n = 4.6 M takes 3.1–3.3 s on an iPhone 15 Pro
and 5.2–8.2 s on an iPhone 12 mini; 3024×2268 / n = 10.1 M takes
7.7–8.6 s and 11.8–16.3 s).
A full `n × 2^h` traceback table does not fit a phone at these sizes
(4.8 GB at n = 4.6 M); implementations can keep checkpoints of the
state costs and recompute segments during the traceback, which yields
the same stego bits in `O(√n · 2^h)` memory.

### 4.2 Coding rate

The fixed sub-matrix width `w = 12` (§4.1) directly pins the embedding
rate at `α = 1/w = 1/12 ≈ 0.0833` bits per AC slot, zeros included
(errata 2026-11-04: not per non-zero AC coefficient). The encoder MUST NOT vary `α`;
the decoder MUST assume `α = 1/12`.

The full parity-check matrix `H` is constructed from `Ĥ` by staggered
diagonal repetition per Filler-Judas-Fridrich 2011 §III: the sub-matrix
slides one row at a time, contributing `w = 12` columns of cover bits
per row of `H`. For `n` cover bits, the resulting `H` is
`m × n` where `m = n / 12` (rounded; padding handled per the cited
section).

Stecho modes **pad** the message bit stream to exactly
`8 × floor(floor(N / 12) / 8)` bits regardless of payload size (errata
2026-11-04: the stream is whole bytes; the reference decoder and the Swift
engine both use this count) (see `open-v1.md` and `stealth-v1.md`
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
embedded_bytes = floor(floor(N / 12) / 8)
embedded_bits  = 8 × embedded_bytes
```

Anything beyond — alternate `w`, adaptive rate, multi-rate
constructions — is out of v1 scope and would require a new layer spec
version (that is layer v2, §V2.5).

In bytes:

```
practical_capacity_bytes = floor(floor(N / 12) / 8) - mode_overhead
```

(Errata 2026-11-04: the formula used `α_target × N / 8` with
`α_target = 0.08`; v1 has no `α` other than `1/12`.)

where `N` is the position count from §2 and `mode_overhead` is the
fixed header size of the calling mode (`open-v1`: see that spec;
`stealth-v1`: see that spec).

> Pre-implementation estimates, kept as written. Only the `1/12` row
> exists in v1; the others never shipped, and the `N` values are rough.
>
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

- **Modern CNN-class steganalysis.** (Note 2026-11-04: the figures in this
  item mix v1's per-slot rate with literature rates per non-zero AC
  coefficient, so they likely understate v1's detectability; see
  proposal §1 and `../docs/experiment-steganalysis.md`. For v2 see
  §V2.12.) SOTA detectors (SRNet, GBRAS-Net,
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
| bpac            | Bits per AC coefficient; v1's rate `1/12` counts every AC slot, zeros included (errata 2026-11-04) |
| Daubechies-8    | The 8-tap orthogonal wavelet `db8`, used by J-UNIWARD residuals |
| J-UNIWARD       | JPEG Universal Wavelet Relative Distortion (Holub-Fridrich 2014) |
| permutation `π` | A bijection of `[0, N)` over the canonical AC list, mode-supplied |
| STC             | Syndrome-Trellis Codes (Filler-Judas-Fridrich 2011)             |
| sub-matrix `Ĥ`  | The small bit-vector pattern that, when staggered, builds the full parity-check matrix `H` |
| wet cost        | Distortion `10¹³` flagging an unembeddable coefficient           |
