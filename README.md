# Stecho Wire-Format Specification

<!-- public-mirror-banner -->

> **Public mirror.** This repository is automatically synchronised from
> the `spec/` directory of the (private) Stecho source tree. Filing
> issues against the spec here is fine; canonical edits happen upstream
> and propagate on every push to Stecho's `main`.

This directory is the **normative specification** of the data formats
Stecho embeds inside JPEG photos. It exists so that anyone — auditor,
journalist, paranoid user — can:

1. Read the spec and understand bit-for-bit what is on the wire.
2. Run a reference decoder on a real Stecho JPEG.
3. Compare against test vectors emitted by the shipping Swift engine.

If the binary on your phone does anything different from what is
described here, that is a bug.

## Layout

| Path | What it covers |
|------|----------------|
| [`juniward-layer.md`](juniward-layer.md) | Shared by both modes. Maps a message bit stream to AC DCT LSB modifications via J-UNIWARD content-adaptive distortion + Syndrome-Trellis Codes (STC). |
| [`open-v1.md`](open-v1.md)               | Open mode framing — public, no privacy. Used by the free tier. |
| [`stealth-v1.md`](stealth-v1.md)         | Stealth mode framing — password-derived permutation + AES-256-GCM. Used by Pro. |
| [`reference/python/`](reference/python/) | Independent Python reference decoder. Run it against `test-vectors/` to verify your decoder is bit-compatible. |
| [`test-vectors/`](test-vectors/)         | Known JPEGs + passwords + expected `(type, body)`. Emitted by the Python encoder; the Swift decoder reads them bit-for-bit on every CI build (`CrossImplVectorsTests`). |

## Stability

Versioned by format. `juniward-layer` is frozen as v1 on first ship.
The two mode files (`open-v1`, `stealth-v1`) are versioned independently
— both currently target v1 with the same embedding layer underneath.

Any incompatible change to the embedding layer requires a new layer
spec file (e.g. `juniward-layer-v2.md`) and corresponding mode-version
bumps. Decoders for future versions MAY attempt v1 as a fallback after
their own version fails (graceful degradation), but a v1 decoder MUST
NOT attempt to interpret a v2 stream.

The encoder side is **not** part of this spec: an attacker who can
choose what to embed already has the password, so encoder behaviour is
implementation detail. Only the decode path is normative.

## How the layer + mode files compose

```
              ┌──────────────────────────────┐
   modes →    │ open-v1.md or stealth-v1.md  │   ← message framing,
              │ (permutation, header, AES)   │     mode-specific
              └──────────────┬───────────────┘
                             │ message_bits + π
                             ▼
              ┌──────────────────────────────┐
   layer →    │       juniward-layer.md      │   ← coefficient choice,
              │ (J-UNIWARD costs + STC)      │     content-adaptive
              └──────────────┬───────────────┘
                             │ DCT coef LSB flips
                             ▼
                          JPEG bytes
```

A decoder reads the JPEG, derives the permutation from the mode (either
by knowing the public open-mode permutation or by computing the
password-derived stealth permutation), walks AC coefficients in
permuted order to recover the message bit stream via STC, then hands
that bit stream back up to the mode for parsing.

## A note on transport

How a Stecho JPEG reaches the recipient is a separate concern from the
wire format and is out of scope here. The reference decoder accepts
JPEG bytes from any source. For the shipping iOS app's actual transport
(image attachment via `MSConversation.insertAttachment`) and the
empirical findings behind that choice, see
[`../docs/experiment-jpeg-imessage-survival.md`](../docs/experiment-jpeg-imessage-survival.md)
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

Copyright 2026 Pavel Khudiakov (OneGoodMan Studio); see [`NOTICE`](NOTICE).
Re-implementing the format in another language is exactly what this
repository is for — no permission needed, attribution appreciated.
