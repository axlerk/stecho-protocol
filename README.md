# Stecho Wire-Format Specification

<!-- public-mirror-banner -->

> **Public mirror.** This repository is automatically synchronised from
> the `spec/` directory of the (private) Stecho source tree. Filing
> issues against the spec here is fine; canonical edits happen upstream
> and propagate on every push to Stecho's `main`.

This directory is the **normative specification** of the data formats
[Stecho](https://onegoodman.studio/stecho) embeds inside JPEG photos. It exists so that anyone — auditor,
journalist, paranoid user — can:

1. Read the spec and understand bit-for-bit what is on the wire.
2. Run a reference decoder on a real Stecho JPEG.
3. Compare against test vectors emitted by the shipping Swift engine.

If the binary on your phone does anything different from what is
described here, that is a bug.

## Layout

| Path | What it covers |
|------|----------------|
| [`juniward-layer.md`](juniward-layer.md) | Shared by both modes. Maps a message bit stream to AC DCT LSB modifications via J-UNIWARD content-adaptive distortion + Syndrome-Trellis Codes (STC). Holds layer **v2** (§V2.1–§V2.13, current draft, with its open items at the top) and layer **v1** (§1–§9, frozen). |
| [`open-v2.md`](open-v2.md)               | Open mode on layer v2 — public, no privacy. Used by the free tier. |
| [`stealth-v2.md`](stealth-v2.md)         | Stealth mode on layer v2 — password-derived permutation + AES-256-GCM. Used by Pro. Also the decoder dispatch order across modes and versions (§8). |
| [`open-v1.md`](open-v1.md)               | Open mode on layer v1 (frozen; readable). |
| [`stealth-v1.md`](stealth-v1.md)         | Stealth mode on layer v1 (frozen; readable). |
| [`reference/python/`](reference/python/) | Independent Python reference encoder and decoder for v1 and v2. Run it against `test-vectors/` to verify your decoder is bit-compatible. |
| [`test-vectors/`](test-vectors/)         | Known JPEGs + passwords + expected `(type, body)`, v1 and v2 (each entry names its layer; v2 entries also the rung). Emitted by the Python encoder; the Swift decoder reads the v1 set on every CI build (`CrossImplVectorsTests`); the v2 set is for the Swift v2 engine. |

## Stability

Versioned by format. Layer v1 and its modes (`open-v1`, `stealth-v1`)
are frozen. Layer v2 is the incompatible successor (non-zero cover,
permutation in both modes, a five-rung rate ladder) and has its own mode
files (`open-v2`, `stealth-v2`); it is a draft until the open items listed
at the top of `juniward-layer.md` close, then it is frozen too. Both
layer versions live in `juniward-layer.md`, v1 under its original
section numbers.

Decoders for v2 MAY attempt v1 as a fallback after v2 fails (order in
`stealth-v2.md` §8), but a v1 decoder MUST NOT attempt to interpret a v2
stream. Open streams carry a version byte (`0x01`, `0x02`); stealth
streams carry none and are told apart by which version authenticates.

The encoder algorithm is **not** part of this spec: an attacker who can
choose what to embed already has the password, so encoder behaviour is
implementation detail. The decode path is normative, and so, in v2, is
what makes a carrier decodable (`juniward-layer.md` §V2.7: the zero set
stays the same). Costs (J-UNIWARD, or SI-UNIWARD when the encoder
quantises the pixels itself) decide detectability, not decodability.

## How the layer + mode files compose

```
              ┌──────────────────────────────┐
   modes →    │ open-v2.md or stealth-v2.md  │   ← message framing,
              │ (permutation, header, AES)   │     mode-specific
              └──────────────┬───────────────┘
                             │ message_bits + π
                             ▼
              ┌──────────────────────────────┐
   layer →    │   juniward-layer.md (v2)     │   ← coefficient choice,
              │ (J-UNIWARD costs + STC,      │     content-adaptive
              │  five-rung rate ladder)      │
              └──────────────┬───────────────┘
                             │ DCT coef LSB flips
                             ▼
                          JPEG bytes
```

A v2 decoder reads the JPEG, lists the non-zero AC coefficients, derives
the permutation from the mode (the public open-mode key or the
password-derived stealth key), and for each of the five rungs recovers a
stream via STC and hands it to the mode, which accepts the first rung whose
frame is valid. v1 is the same picture with all AC slots, one fixed rate,
and the identity order in open mode.

## A note on transport

How a Stecho JPEG reaches the recipient is a separate concern from the
wire format and is out of scope here. The reference decoder accepts
JPEG bytes from any source. For the shipping iOS app's actual transport
(image attachment via `MSConversation.insertAttachment`, carrier encoded
with Apple's sharing colour profile so iMessage does not re-encode it) and
the empirical findings behind that choice, see
[`../docs/experiment-device-transport.md`](../docs/experiment-device-transport.md)
and [`THREAT_MODEL.md`](THREAT_MODEL.md) §4.3.

## License

| What | License | Text |
|------|---------|------|
| Reference decoder (`reference/`) | Apache-2.0 | [`LICENSE`](LICENSE) |
| Specification text (`*.md` in this directory) | CC BY 4.0 | [`LICENSE-DOCS`](LICENSE-DOCS) |
| [`THREAT_MODEL.md`](THREAT_MODEL.md) | CC BY 4.0 | [`LICENSE-DOCS`](LICENSE-DOCS) |
| Test vectors (`test-vectors/`) | CC BY 4.0 | [`LICENSE-DOCS`](LICENSE-DOCS) |
| Swift cost-map port (`reference/swift/JUNIWARDCost.swift`, derived from conseal) | MPL-2.0 | [`reference/swift/LICENSE-MPL-2.0`](reference/swift/LICENSE-MPL-2.0) |
| `legal/` (privacy policy, support page) | not covered — all rights reserved | — |

The Python reference decoder imports [conseal](https://github.com/uibk-uncover/conseal)
(MPL-2.0) at run time as a dependency; no conseal code is copied into it. The Swift
cost-map port, by contrast, is derived from conseal's code and therefore stays
under MPL-2.0 (see the table).

Copyright 2026 Pavel Khudiakov ([OneGoodMan Studio](https://onegoodman.studio)); see [`NOTICE`](NOTICE).
Re-implementing the format in another language is exactly what this
repository is for — no permission needed, attribution appreciated.
