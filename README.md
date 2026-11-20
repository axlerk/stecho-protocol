# Stecho Wire-Format Specification

<!-- public-mirror-banner -->

> **Public mirror.** This repository is automatically synchronised from
> the `spec/` directory of the (private) Stecho source tree. Filing
> issues against the spec here is fine; canonical edits happen upstream
> and propagate on every push to Stecho's `main`.

**Status:** draft. Embedding layer v2 with `open-v2` and `stealth-v2` is
what the app writes and reads; it stays a draft until the open items at the
top of `juniward-layer.md` close.

This directory is the normative specification of the formats
[Stecho](https://onegoodman.studio/stecho) hides inside a JPEG photo. It
exists so that anyone can:

1. Read the spec and see what is on the wire.
2. Run the reference decoder (`reference/python/`) on a real photo.
3. Compare the result against the test vectors (`test-vectors/`).

If the app does anything different from what is written here, one of the two
has a bug: please report it (below).

**Stecho hides what a message says. It does not hide that a photo carries
one**: the longer the message, the easier a statistical test finds it
([`THREAT_MODEL.md`](THREAT_MODEL.md), §3.1).

## Layout

| File | What it covers |
|------|----------------|
| [`juniward-layer.md`](juniward-layer.md) | From a byte stream to changes of JPEG coefficients: which coefficients, the five rates, the costs and the syndrome-trellis code. Shared by both modes. Layer **v2** is §V2.1–§V2.13, with its open items at the top; the retired layer v1 is §1–§9, kept as history. |
| [`open-v2.md`](open-v2.md) | Open mode: public, no privacy. |
| [`stealth-v2.md`](stealth-v2.md) | Stealth mode: a password-derived order and AES-256-GCM. Also the order in which a decoder tries the modes (§8). |
| [`open-v1.md`](open-v1.md), [`stealth-v1.md`](stealth-v1.md) | **Retired** on 2026-11-10. The formats of one TestFlight build, kept as history; no decoder reads them. |
| [`reference/python/`](reference/python/) | Reference encoder and decoder for v2; no code shared with the app. |
| [`test-vectors/`](test-vectors/) | Photos, passwords and the expected `(type, body)`, written by the Python encoder; `test-vectors/swift-v2/` holds photos written by the app's engine, for the Python decoder. |

How the files fit together:

```
              ┌──────────────────────────────┐
   modes →    │ open-v2.md or stealth-v2.md  │   ← message framing,
              │ (order, header, AES)         │     mode-specific
              └──────────────┬───────────────┘
                             │ message bits + order
                             ▼
              ┌──────────────────────────────┐
   layer →    │   juniward-layer.md (v2)     │   ← coefficient choice,
              │ (costs + codes, five rates)  │     content-adaptive
              └──────────────┬───────────────┘
                             │ changed coefficients
                             ▼
                          JPEG bytes
```

A v2 decoder reads the JPEG, lists the non-zero AC coefficients, derives the
order from the mode (a public key in open mode, the password in stealth
mode), and for each of the five rates recovers a stream and hands it to the
mode, which accepts the first whose frame is valid.

## What is measured and what may change

**Measured:** how well detectors find a photo with a message at each rate,
and that iMessage delivers the carrier unchanged between two iPhones. The
numbers, with their sample sizes and dates, are in the threat model (§3.1,
§3.4); they replace the simulated figures that `juniward-layer.md` §V2.12
still quotes.

**May change:** the items listed under "Open" at the top of
`juniward-layer.md`. Until they close, layer v2 is a draft.

## Stability

Versioned by format. Once layer v2 is frozen, a change that breaks a decoder
gets a new version number and a new file. Open streams carry a version byte
(`0x02` for `open-v2`); stealth streams carry none and are told apart by
which stream authenticates.

Layer v1 (`open-v1`, `stealth-v1`: every AC slot, one fixed rate) was
written by one TestFlight build and never reached a release. It was retired
on 2026-11-10 with no compatibility period: the app and the reference
decoders no longer read it, and a v1 photo decodes as a photo with nothing
in it. Its documents stay because v2 reuses parts of them (the stealth order
key and its salt label `stecho-stealth-v1-perm-salt` are part of the v2
format); git keeps the old decoders.

Only the decode path is normative, and in v2 so is what keeps a carrier
decodable (`juniward-layer.md` §V2.7). An attacker who can choose what to
embed already has the password, so how an encoder picks its changes is
implementation detail: the costs decide how detectable a photo is, not
whether it decodes.

## A note on transport

How a photo reaches the recipient is outside the wire format: the reference
decoder takes JPEG bytes from any source, and any transport that delivers
the file byte for byte will do. The app sends the JPEG as an image
attachment (`MSConversation.insertAttachment`), written in Apple's sharing
colour profile so that Messages does not re-encode it. What was measured
about delivery is in the threat model, §3.4.

## Threat model and reports

This directory defines a wire format, not a threat model. What the formats
protect, what they do not and how we know is in
[`THREAT_MODEL.md`](THREAT_MODEL.md).

Found a difference between the app and this spec? Open an issue at
<https://github.com/axlerk/stecho-protocol/issues>. For an attack on the
format, write first to hello@onegoodman.studio with `[SECURITY]` in the
subject.

## License

| What | License | Text |
|------|---------|------|
| Reference decoder (`reference/python/`) | Apache-2.0 | [`LICENSE`](LICENSE) |
| Specification text (`*.md` in this directory) | CC BY 4.0 | [`LICENSE-DOCS`](LICENSE-DOCS) |
| Test vectors (`test-vectors/`) | CC BY 4.0 | [`LICENSE-DOCS`](LICENSE-DOCS) |
| [`THREAT_MODEL.md`](THREAT_MODEL.md), published with the spec | CC BY 4.0 | [`LICENSE-DOCS`](LICENSE-DOCS) |
| Swift cost-map port (`reference/swift/JUNIWARDCost.swift`, derived from conseal) | MPL-2.0 | [`reference/swift/LICENSE-MPL-2.0`](reference/swift/LICENSE-MPL-2.0) |
| `legal/` (privacy policy, support page) | not covered: all rights reserved | — |

The Python reference imports
[conseal](https://github.com/uibk-uncover/conseal) (MPL-2.0) at run time and
copies none of its code. The Swift cost-map port is derived from conseal's
code and stays under MPL-2.0.

Copyright 2026 Pavel Khudiakov
([OneGoodMan.studio](https://onegoodman.studio)); see [`NOTICE`](NOTICE).
Writing your own implementation of the format is what this repository is
for: no permission needed, attribution appreciated.
