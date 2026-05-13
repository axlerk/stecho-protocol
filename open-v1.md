# Open Mode v1 (`open-v1`)

The mode used by **free-tier** Stecho. The carrier is a publicly-readable
Stecho JPEG: anyone with the Stecho app (or a conforming decoder) can
extract the payload without any password.

Open mode is **not a privacy feature.** It exists to give free users a
way to send hidden voice / text messages with the same UX as stealth
mode, while preserving Pro as the paywall for content confidentiality.
This mirrors Stiger's `open-v1` decision: the bytes are hidden in the
carrier (you can't see them by opening the JPEG in Photos), but the app
doesn't pretend they're protected.

This document defines the wire format. The shared embedding layer
(J-UNIWARD distortion + STC) is described in
[`juniward-layer.md`](juniward-layer.md); this document only specifies
how open mode parameterises that layer.

> **Notation.** All multi-byte integer fields are little-endian unless
> stated otherwise. `||` is byte-string concatenation.

## 1. Inputs

- `jpeg` — baseline or progressive JPEG carrier.
- `type_tag` — `0x01` (text) or `0x02` (audio-opus); other values rejected.
- `body` — the payload bytes. Length: any value that fits the carrier's
  open-mode capacity (§5).

No password. No randomness on the encoder side (the AES wrapper is absent).

## 2. Permutation

Open mode uses the **identity permutation** `π_open(i) = i` over the
canonical AC position list defined in
[`juniward-layer.md`](juniward-layer.md) §2. There is no password input
to derive a permutation from, and open mode is publicly readable by
design.

## 3. Embedding rate

Open mode uses **`α = 0.08`** bits per non-zero AC coefficient, fixed
at the v1 protocol level. The encoder MUST NOT vary `α`; the decoder
MUST assume `α = 0.08`.

`α = 0.08` is chosen to cover the product target of 40 / 60 / 90 s
voice messages on common iPhone carriers — see capacity table in §5.
The choice trades a higher modification rate (and slightly higher
academic CNN-detection accuracy) for the ability to fit a typical
1-minute voice note on a stock 12 MP iPhone photo. See
`juniward-layer.md` §8 for the threat-model implications.

## 4. Plaintext stream layout

The byte stream extracted via STC (§6 of layer spec) has this layout:

```
offset    size       field
------    ----       -----------------------------------------------
 0         4         magic        ASCII "SECO" (0x53, 0x45, 0x43, 0x4F)
 4         1         version      0x01 — protocol version (this spec)
 5         1         type_tag     0x01=text, 0x02=audio-opus
 6         4         length       LE uint32, byte count of body
10      length       body         payload bytes
10+length   rest     padding      MUST be ignored by decoder; encoder
                                  fills with cryptographically random
                                  bytes (looks like a stealth message)
```

Total header: 10 bytes. The padding ensures the embedded stream length
equals `floor(α × N / 8)` regardless of `body` size, so an external
observer cannot distinguish a short open-mode payload from a long one
by looking at modification statistics.

`length` MUST satisfy `0 ≤ length ≤ floor(α × N / 8) - 10`. Anything
outside the range is treated as a malformed open-mode JPEG and triggers
fallback to stealth-mode decode attempt (§7 below).

## 5. Capacity

```
open_capacity_bytes = floor(0.08 × N / 8) - 10
```

where `N` is the position count from layer spec §2. For typical iPhone
carriers:

| Carrier               | N (approx) | open capacity | Voice (12 kbps Opus) |
|-----------------------|------------|---------------|----------------------|
| 512×512               | 250 K      | 2.4 KB        | ~1.5 s               |
| 1024×1024             | 1.0 M      | 10 KB         | ~6 s                 |
| 2048×2048             | 4.0 M      | 40 KB         | ~25 s                |
| 4032×3024 (12 MP)     | 14 M       | 140 KB        | ~87 s                |
| 4032×3024 (24 MP)     | 28 M       | 280 KB        | ~175 s               |

Encoder MUST refuse messages exceeding `open_capacity_bytes`.

## 6. Encoder algorithm (informative)

```
fn encode_open(jpeg, type_tag, body) -> jpeg_out:
    # 1. Build the plaintext stream.
    if len(body) > open_capacity_bytes:
        throw insufficient_capacity
    stream = b"SECO" || [0x01] || [type_tag] || u32_le(len(body)) || body
    stream_size = floor(0.08 × N / 8)
    stream || csprng(stream_size - len(stream))    # pad with random

    # 2. Convert to bit stream.
    bits = bytes_to_bits(stream, msb_first=true)

    # 3. Embed via the layer with identity permutation.
    return juniward_layer.encode(
        jpeg     = jpeg,
        pi       = identity_permutation(N),
        message  = bits,
        alpha    = 0.08,
    )
```

## 7. Decoder algorithm (normative)

```
fn decode_open(jpeg) -> Option<(type_tag, body)>:
    spectral = parse_jpeg(jpeg)
    if spectral == None: return None
    N = position_count(spectral)
    stream_size_bits = floor(0.08 × N)
    stream_size_bytes = stream_size_bits // 8

    # STC-decode the entire open-mode stream.
    bits = juniward_layer.decode(
        jpeg    = jpeg,
        pi      = identity_permutation(N),
        message_length = stream_size_bits,
        alpha   = 0.08,
    )
    stream = bits_to_bytes(bits, stream_size_bytes)

    # Parse header.
    if len(stream) < 10: return None
    if stream[0..4] != b"SECO": return None
    if stream[4] != 0x01: return None     # unsupported version
    type_tag = stream[5]
    if type_tag not in {0x01, 0x02}: return None
    length = u32_le(stream[6..10])
    if length > stream_size_bytes - 10: return None
    body = stream[10..10+length]
    return Some((type_tag, body))
```

A `None` return triggers the caller to attempt stealth-mode decode
(see [`stealth-v1.md`](stealth-v1.md)) if the user has provided a
password.

## 8. Threat model

Open mode does not protect content. Anyone with the Stecho app, or any
conforming decoder, recovers the body from any open-mode Stecho JPEG.

The carrier still hides the payload from someone *without* the Stecho
app (the JPEG looks like an ordinary photo when viewed normally), but
this is concealment from casual inspection — not from anyone who
suspects a Stecho photo and runs a decoder.

Use stealth mode when content protection matters. Open mode exists for:

- Free-tier UX parity (a user without Pro can still send hidden
  messages, just publicly-readable ones).
- "Playful" use cases where the recipient is in on the game and
  doesn't need a shared password.
- The "I want a hidden message and don't really mean it" case.

## 9. Stability

`open-v1` is frozen on first ship. Incompatible changes require a new
version (`open-v2.md`). The magic prefix `SECO` is reserved for v1; a
future v2 MUST use a different prefix or version byte to prevent
ambiguity.

## 10. Glossary

| Term            | Definition                                                       |
|-----------------|------------------------------------------------------------------|
| identity permutation | `π(i) = i` — positions visited in canonical scan order      |
| SECO magic      | The 4-byte prefix `0x53 0x45 0x43 0x4F` identifying open-mode v1 |
