# Open Mode v2 (`open-v2`)

The mode used by **free-tier** Stecho on embedding layer v2. Anyone with
Stecho, or any conforming decoder, reads the payload without a password.
As in v1, open mode is **not a privacy feature**: the bytes are hidden in
the photo, not protected (§8).

This document defines how open mode frames its message on top of
[`juniward-layer.md`](juniward-layer.md) layer v2 (§V2.1–§V2.13). It
replaces [`open-v1.md`](open-v1.md) (retired 2026-11-10, not read by any
decoder; §7.2).

Status: draft. The open items of the layer apply, in particular the rate
ladder (O1) and the sub-matrices (O4) ([`juniward-layer.md`](juniward-layer.md),
"Open").

> **Notation.** All multi-byte integer fields are little-endian unless
> stated otherwise. `||` is byte-string concatenation.

## 1. Inputs

- `jpeg` — baseline or progressive JPEG carrier (or pixels, for an encoder
  that quantises them itself).
- `type_tag` — `0x01` (text, UTF-8) or `0x02` (audio-opus); other values
  rejected. The audio body is the app's Opus container, which this spec
  does not define (layer O5).
- `body` — the payload bytes, at most the capacity of the highest rung the
  encoder allows (§5).

No password. The encoder needs randomness only for the padding (§4).

## 2. Permutation

The layer's keyed permutation (§V2.4) with the public key and info tag

```
key  = SHA-256(ASCII "stecho-open-v2-perm-key")
     = cfd8f182773909afb32cbdf6e85d7b060540b01e5d9ea2d82a02654d5ce1f369
info = ASCII "stecho-open-v2-perm"                       # 19 bytes
```

over the `n` cover elements. Anyone can compute it; it exists only to
spread the cover elements evenly over the code (v1 open mode used the
identity order, which clustered usable coefficients and forced changes
into zeros).

## 3. Rate

Open mode uses the layer's rate ladder (§V2.5): rung `k` gives a stream
of `L_k = floor(n × q_k / (8 × d_k))` bytes. The encoder picks the rung
(§6); the decoder tries rungs 1 to 5 in that order (§7).

## 4. Stream layout

The `L_k`-byte stream of the chosen rung:

```
offset    size       field
------    ----       -----------------------------------------------
 0         4         magic        ASCII "SECO" (0x53, 0x45, 0x43, 0x4F)
 4         1         version      0x02 — this spec (open-v1 is 0x01)
 5         1         type_tag     0x01=text, 0x02=audio-opus
 6         4         length       LE uint32, byte count of body
10      length       body         payload bytes
10+length   rest     padding      to L_k bytes; MUST be ignored by the
                                  decoder; the encoder fills it with
                                  random bytes
```

The layout is open-v1's with version `0x02`. The stream is only as long as
the rung, not the whole carrier: v1's full-capacity padding is gone
(proposal §3.2), and the rung itself reveals the message size to within 2×
to anyone who decodes it.

`length` MUST satisfy `length ≤ L_k − 10`.

## 5. Capacity

```
open_capacity(k) = L_k − 10
```

`n` is the carrier's non-zero AC count (§V2.3), so capacity depends on the
photo. Free = half the photo (D5): with the default Balanced preset, a
free open-mode message may use rungs 1–3 (layer §V2.5.3). The encoder MUST
refuse a body larger than `open_capacity` of its highest allowed rung.

## 6. Encoder (informative)

```
fn encode_open_v2(carrier, type_tag, body, max_rung) -> jpeg_out:
    cover = layer_v2_cover(carrier); n = len(cover)
    k = smallest rung in 1 .. max_rung with L_k ≥ 10 and len(body) ≤ L_k − 10
    if no such k: throw insufficient_capacity
    stream = b"SECO" || [0x02] || [type_tag] || u32_le(len(body)) || body
    stream = stream || random(L_k − len(stream))
    return layer_v2_encode(carrier, open_permutation, stream, k)
```

The encoder may pick a higher rung than the smallest that fits; decoders
accept it.

## 7. Decoder (normative)

### 7.1 open-v2

```
fn decode_open_v2(jpeg) -> Option<(k, type_tag, body)>:
    for (k, stream) in layer_v2_streams(jpeg, open_permutation, min_bytes = 10):
        if stream[0..4] != b"SECO": continue
        if stream[4] != 0x02: continue
        type_tag = stream[5]
        if type_tag not in {0x01, 0x02}: continue
        length = u32_le(stream[6..10])
        if length > len(stream) − 10: continue
        return Some((k, type_tag, stream[10 .. 10 + length]))
    return None
```

Rungs are tried in ascending order and the first valid one wins
([`juniward-layer.md`](juniward-layer.md) §V2.5.2). A decoder that also
reports which rung it found (the reference does) exposes nothing new: the
rung is readable by anyone in open mode.

### 7.2 Retired open-v1

`open-v1` ([`open-v1.md`](open-v1.md)) was retired on 2026-11-10 and no
decoder tries it: a v1 carrier (version `0x01`, all AC slots in identity
order) reads as no payload. The two never accepted the same stream anyway:
the v1 decoder read all AC slots in identity order and required version
`0x01`, the v2 decoder reads the non-zero cover in the open-v2 order and
requires `0x02`. Full dispatch, with stealth mode:
[`stealth-v2.md`](stealth-v2.md) §8.

## 8. Threat model

As open-v1 (§8 there): anyone with a conforming decoder recovers the body.
The photo looks ordinary when viewed; that is concealment from casual
inspection, not protection.

What v2 changes:

- The rung is visible to anyone who decodes: message size to within 2×.
- The permutation is public, so it adds no secrecy. Detection is
  statistical in both modes; open and stealth carriers at the same rung
  use the same layer, costs and rate, so they should be equally
  detectable (inferred, not measured; layer §V2.12).

Use stealth mode when content matters.

## 9. Stability

`open-v2` is a draft until the layer's open items that touch the wire
format (O1, O4) are closed; then it is frozen. Incompatible changes after
that need `open-v3` and version byte `0x03`.

## 10. Glossary

| Term | Definition |
|---|---|
| SECO magic | The 4-byte prefix `0x53 0x45 0x43 0x4F` of open-mode streams, v1 and v2 |
| version `0x02` | Marks an open-v2 stream; `0x01` is open-v1 |
| rung `k`, `L_k` | Rate step and stream size of the layer (§V2.5) |
| open permutation | Layer permutation with the public key of §2 |
