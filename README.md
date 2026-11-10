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
| [`juniward-layer.md`](juniward-layer.md) | Shared by both modes. Maps a message bit stream to AC DCT LSB modifications via J-UNIWARD content-adaptive distortion + Syndrome-Trellis Codes (STC). Holds layer **v2** (§V2.1–§V2.13, current draft, with its open items at the top) and, as history, retired layer **v1** (§1–§9). |
| [`open-v2.md`](open-v2.md)               | Open mode on layer v2 — public, no privacy. Used by the free tier. |
| [`stealth-v2.md`](stealth-v2.md)         | Stealth mode on layer v2 — password-derived permutation + AES-256-GCM. Used by Pro. Also the decoder dispatch order across modes (§8). |
| [`open-v1.md`](open-v1.md), [`stealth-v1.md`](stealth-v1.md) | **Retired** (2026-11-10). The formats of one TestFlight build, kept as history; no shipping or reference decoder reads them (see "Retired: layer v1" below). |
| [`reference/python/`](reference/python/) | Independent Python reference encoder and decoder for v2. Run it against `test-vectors/` to verify your decoder is bit-compatible. |
| [`test-vectors/`](test-vectors/)         | Known JPEGs + passwords + expected `(type, body)`, all layer v2 (each entry also names the rung). Emitted by the Python encoder; the Swift decoder reads the set (`CrossImplVectorsTests`). `test-vectors/swift-v2/` holds v2 carriers emitted by the Swift encoder, for the Python decoder. |

## Stability

Versioned by format. Layer v2 and its modes (`open-v2`, `stealth-v2`) are
the current formats (non-zero cover, permutation in both modes, a five-rung
rate ladder); layer v2 is a draft until the open items listed at the top of
`juniward-layer.md` close, then it is frozen. An incompatible change
requires a new version number and a new spec file. `juniward-layer.md`
still holds the retired layer v1 under its original section numbers (§1–§9),
because the v2 text cites them.

Open streams carry a version byte (`0x02` for open-v2; `0x01` was open-v1);
stealth streams carry none and are told apart by which stream authenticates.
The dispatch order of a decoder is `stealth-v2.md` §8.

### Retired: layer v1

Layer v1 (`open-v1`, `stealth-v1`: every AC slot, one fixed rate of `1/12`,
identity order in open mode) was written by exactly one TestFlight build,
build 1, and never reached a release: no App Store version contains it. The
owner retired it on 2026-11-10, without a compatibility period, because no
installed base was worth carrying it for (the same decision, for the same
reason, that retired Stiger's previous format on 2026-11-08). The shipping
Swift decoder and the reference decoders no longer read it, and a v1
carrier decodes to "no hidden data", exactly as a JPEG without a payload
does; the test vectors of v1 were removed from `test-vectors/`. The
documents `open-v1.md`, `stealth-v1.md` and `juniward-layer.md` §1–§9 stay
as history, unchanged apart from a notice, because v2 reuses parts of them
(the stealth permutation key and its salt label `stecho-stealth-v1-perm-salt`
are part of the v2 wire format). Git history holds the old decoders. A photo
made by TestFlight build 1 does not open in a later build.

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
frame is valid.

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
