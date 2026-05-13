# Stecho — Threat Model

This document states what Stecho defends against, what it does **not**
defend against, and the assumptions behind those guarantees. Read it
before trusting the app with anything that matters.

If you find a gap between this document and the implementation, the
implementation is wrong — please open an issue.

For the byte-for-byte wire format and an independent reference decoder
you can run yourself, see [`spec/`](spec/README.md).

## TL;DR

**English.** Stecho encrypts a short voice or text message
(AES-256-GCM, password-derived via PBKDF2-SHA256-600k) and hides the
ciphertext in the quantized DCT coefficients of an ordinary JPEG photo
via J-UNIWARD content-adaptive distortion + Syndrome-Trellis Codes
(STC) at fixed embedding rate `α = 1/12 ≈ 0.083`, then sends the photo
through iMessage as a regular image attachment. **What it protects:**
message content (unreadable without the password) and the wire profile
(no magic bytes, no plaintext length, constant embedding rate per
carrier). **What it does not:** trained CNN-class steganalysis can
detect that *some* J-UNIWARD modification happened (without recovering
the message); a compromised device, a forensic Keychain dump,
screenshots, or iMessage recompression all defeat or destroy the
payload. **Open mode** (no password) is publicly readable by anyone
with Stecho and is not a privacy feature. **No forward secrecy:** a
password leak retroactively decrypts every prior message under that
password. Read the rest before relying on Stecho for anything serious.

**По-русски.** Stecho шифрует короткое голосовое или текстовое
сообщение (AES-256-GCM, пароль растягивается через
PBKDF2-SHA256-600k) и прячет шифротекст в квантованных DCT-
коэффициентах обычной JPEG-фотографии алгоритмом J-UNIWARD + STC при
фиксированной скорости встраивания `α = 1/12 ≈ 0.083`, после чего
отправляет фотографию через iMessage как обычное вложение. **Что
защищает:** содержимое сообщения (нечитаемо без пароля) и профиль на
проводе (никаких магических байт, никакой plaintext-длины, скорость
встраивания постоянна для данного носителя). **Чего не защищает:**
обученный CNN-стегоанализ видит *сам факт* J-UNIWARD-модификации (без
чтения сообщения); компрометация устройства, форензик-дамп Keychain,
скриншоты и пережатие iMessage — всё это либо обходит, либо
уничтожает payload. **Открытый режим** (без пароля) читается любым, у
кого есть Stecho, — это не приватность. **Forward secrecy нет:**
утечка пароля ретроактивно расшифровывает все предыдущие сообщения
под этим паролем. Прочитайте дальше, прежде чем полагаться на Stecho
в серьёзных вещах.

## 1. Scope

Stecho hides short voice messages (up to ~90s of 12 kbps Opus on a
24 MP iPhone-15-Pro carrier, ~55s on a stock 12 MP carrier) or short
text inside JPEG photos and ships them through Apple's iMessage as
ordinary image attachments. There are two modes:

> **Note on transport.** Carriers are shipped as ordinary iMessage
> image attachments (`MSConversation.insertAttachment`). The
> alternative — `MSSticker` objects — aggressively re-encodes and is
> incompatible with any steganography. This is **observed platform
> behaviour, not a security guarantee**; the recompression failure
> mode is covered in §6.3 below. See
> [`docs/experiment-jpeg-imessage-survival.md`](docs/experiment-jpeg-imessage-survival.md)
> for what has been empirically verified.

- **Open mode** ([`spec/open-v1.md`](spec/open-v1.md)) — no password.
  The carrier is a *public* Stecho JPEG. The payload is framed by a
  fixed 4-byte magic + version + type + length, embedded under the
  identity permutation. Anyone with Stecho (or any conforming decoder)
  reads the body. Used as a Pro-feature UX parity layer for free-tier
  users; not a privacy feature.

- **Stealth mode** ([`spec/stealth-v1.md`](spec/stealth-v1.md)) — the
  user has a shared password with the recipient. The body is wrapped
  in AES-256-GCM under a key derived from the password, and the
  resulting blob is laid out in DCT-coefficient LSBs in a
  password-derived permuted order. Without the password the embedded
  bytes are computationally indistinguishable from random noise in
  the LSB stream.

Both modes share the same J-UNIWARD + STC embedding layer
([`spec/juniward-layer.md`](spec/juniward-layer.md)) at the same fixed
embedding rate, so the *number* of modifications a Stecho JPEG carries
is fully determined by the carrier alone, independent of mode or
payload size.

This document only covers the **content-and-transport layer**. App-
side concerns (UI, paywall, biometrics, message draft storage) are
covered in the implementation and in [`AGENTS.md`](AGENTS.md) but only
referenced here where they intersect the cryptographic story.

## 2. What Stealth Mode Defends

### 2.1 Content confidentiality

The plaintext body — voice or text — is encrypted with AES-256-GCM
before being embedded. The encryption key is derived from the
password via PBKDF2-HMAC-SHA256 at 600 000 iterations with a random
16-byte per-message salt. Brute-forcing a single message requires at
minimum `~2 × PBKDF2-HMAC-SHA256-600k` operations per password
candidate (the second PBKDF2 is for the permutation key — see §2.4).

Without the password, the ciphertext is computationally
indistinguishable from random bytes. Modern AES-256-GCM is the
relevant cryptographic primitive; we make no claims stronger than the
underlying primitive's published security.

### 2.2 Content authenticity

AES-GCM produces a 16-byte authentication tag covering the
ciphertext and the AAD (`aes_salt || aes_nonce`). Any tampering with
the embedded stream — coefficient flips, header bytes, position
shuffling — fails tag verification and the decoder returns `None`.
A wrong-password decode and a tampered-stego decode are
indistinguishable to the user.

### 2.3 No wire-format fingerprint

The stealth-mode stream contains **no plaintext magic bytes, no
length field, no version marker** outside the GCM-protected region.
The first bytes (`aes_salt`) are uniformly random per message. A
passive observer with a Stecho-aware decoder cannot fingerprint a
stealth-mode JPEG by scanning the embedded byte order — every byte
in the stream is either random salt/nonce, or random ciphertext, or
the GCM tag.

This is the property Stiger's `stealth-v3` originally aimed for, and
the same one we deliberately preserve here. F-family algorithms that
prepend `STEG` magic bytes (or any fixed marker) are trivially
identifiable; Stecho is not.

### 2.4 Wrong-password indistinguishability

A decoder presented with a Stecho stealth JPEG and the *wrong*
password returns the same `None` result as a decoder presented with
a JPEG that is not a Stecho photo at all. There is no oracle for
"this JPEG contains a Stecho message" that an attacker can probe
faster than the full PBKDF2-bound per-attempt cost.

The pre-AES sanity check on length is intentionally absent (the
length is inside the GCM-protected region), which is the same
oracle-minimization design as Stiger's `stealth-v3`.

### 2.5 No length oracle through embedding rate

Both modes embed at the same fixed `α = 1/12` regardless of payload
size. A 5-byte text and a 1-minute voice note on the same carrier
produce the same number of DCT-coefficient modifications. An
observer with access to many Stecho JPEGs cannot infer payload size
from per-image modification statistics.

### 2.6 Content-adaptive embedding (J-UNIWARD)

Modifications concentrate in textured, high-entropy image regions
where the J-UNIWARD distortion cost is low, and avoid smooth or
predictable regions. This resists detectors that key on uniform-
region histogram perturbations (classical chi-squared, calibration-
aware methods).

## 3. What Open Mode Defends

**Almost nothing.** Open mode hides bytes from someone looking at the
JPEG in Photos (you can't see a hidden message by opening the photo
normally), but anyone with Stecho or a conforming open-mode decoder
will recover the body in milliseconds. The 4-byte `SECO` magic at
the start of the embedded stream is a positive fingerprint — open-
mode JPEGs are *intended* to be recognisable as Stecho photos.

Open mode exists for two reasons:

1. **Free-tier UX parity.** A user without a Stecho Pro subscription
   should be able to send hidden messages with the same UI flow as
   paying users — just publicly-readable ones.
2. **Playful use cases.** "Send a hidden voice note to your friend
   without typing anything visible" — the recipient is in on the
   game, no privacy is being claimed, no shared password is needed.

Use stealth mode when content protection matters. Do not assume open
mode protects anything beyond casual reading of the photo.

## 4. What Stecho Does NOT Defend

### 4.1 Trained CNN-class steganalysis

J-UNIWARD's content-adaptive distortion is the academic state of the
art for JPEG embedding, but it is not undetectable. Modern detectors
(SRNet, GBRAS-Net, Yedroudj-Net) trained on J-UNIWARD-modified
JPEGs at `α = 0.08` detect with accuracy roughly 70-78% on standard
test corpora (BOSSbase, ALASKA II). These figures are recalled from
the academic literature and have not been independently measured by
Stecho.

**An adversary with a steganalysis-trained CNN classifier can, with
non-trivial probability, distinguish a Stecho photo from an ordinary
photo without recovering the content.** Stecho does not claim
otherwise. Content confidentiality (AES-GCM) is unaffected — even a
positive classification doesn't reveal what was hidden — but the
*fact* of hiding may be exposed.

Realistic adversaries with this capability are state-level signal
intelligence agencies and academic stegoanalysis labs. They are not
the bulk of phone-search scenarios (border control, intimate
relationships, employer / school administration), which typically
rely on format-fingerprint detection — a class of attack Stecho
specifically defeats.

> **What we have measured.** Nothing. The detection numbers above are
> from published literature on academic test corpora. Real-world
> detection on iPhone-photo carriers (which are 24 MP color, far from
> BOSSbase's 512×512 grayscale distribution) is likely lower than
> academic numbers — but we have not formally measured it. Treat the
> 70-78% as worst-case upper bound, not a guarantee.

### 4.2 Side channels on the user's device

A compromised device defeats Stecho in many ways the wire format
cannot help with:

- **Keychain dump.** Stecho's password is stored in iOS Keychain with
  `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`. This is good
  hygiene but does not survive a Cellebrite-class forensic
  extraction of an unlocked device. Once the password is dumped,
  every prior message under that password is decrypted retroactively.
  See §5 below.

- **Clipboard / draft persistence.** If the user composes a long
  text message and the OS keyboard caches it, or if a draft is held
  in Stecho's message-compose surface, that plaintext exists on the
  device. Stecho intentionally avoids long-lived plaintext drafts
  (`SharedDefaults.draft*` does not exist by design) but cannot
  prevent OS-level keyboard caching.

- **Screenshots.** The user can screenshot the decoded content;
  iMessage's Screen Time / Restrictions / Memoji recording APIs see
  the screen contents. Stecho does not block screenshots (and could
  not reliably do so even if it tried — third-party apps cannot
  fully suppress the iOS screenshot mechanism).

- **Voiceover / accessibility services.** Anything spoken aloud by
  VoiceOver is captured by the OS audio buses and theoretically
  available to any app with `kAudioObjectPropertyDataSource`-style
  access (limited in practice on iOS, but not zero).

- **Biometric coercion.** A user being physically compelled to
  unlock the device defeats Face ID / Touch ID by definition.
  Stecho's biometric layer is a *consent-friction* gate, not an
  anti-coercion mechanism.

### 4.3 iMessage transport-layer recompression

Stecho assumes the JPEG attachment arrives at the recipient with
**DCT coefficients preserved byte-for-byte**. This is observed
behaviour of `MSConversation.insertAttachment` on current iOS
versions, not a contractual guarantee from Apple. If Apple changes
the iMessage attachment pipeline to recompress JPEGs (re-encode at
different Q, re-quantize, strip metadata), the J-UNIWARD payload is
destroyed and decoders return `None`. See
[`docs/experiment-jpeg-imessage-survival.md`](docs/experiment-jpeg-imessage-survival.md)
for the empirical state.

This is the **single biggest non-cryptographic risk to Stecho.**
There is no mitigation we can build into the wire format if the
transport fails to preserve bytes — by definition. Mitigations are
operational: monitor iOS releases for transport behaviour changes,
keep a documented bench matrix, fall back to alternative file types
(HEIC, PNG) if JPEG is ever broken.

### 4.4 Forward secrecy

Stecho has **no forward secrecy**. A password leak today
retroactively decrypts every prior message under that password.
This is a deliberate design choice — forward secrecy requires
either an ephemeral-key exchange (impossible without an out-of-band
channel besides iMessage itself, which we don't trust either) or
per-message session keys (requires per-message channel state, which
the JPEG-attachment medium doesn't carry).

Rotate passwords if you suspect compromise. Stecho's pairing flow
([`AGENTS.md`](AGENTS.md) references `SecurePairingExchange`) is the
intended channel for password rotation, but it does not give you
forward secrecy either — the new password also has no future-proof
key separation.

### 4.5 Side-channel leakage from file size

Two Stecho photos with the same carrier source but different
payloads will have different JPEG file sizes (because the modified
DCT coefficients compress slightly differently after recompression).
The encoder does **not** size-normalize the output JPEG to a fixed
byte count. An observer with access to both the source carrier and
the resulting Stecho-encoded version could potentially extract
information from the size delta — though in practice this requires
the source to be available, which is an unusual threat model for
iMessage.

If the carrier source is private (never sent elsewhere), this leak
is bounded to "this JPEG is bigger / smaller than typical iPhone
photos" rather than a content oracle.

### 4.6 The recipient's device

Once a Stecho photo reaches the recipient, all the device-side
concerns in §4.2 apply to *their* device too. Stecho cannot defend
content from a malicious or careless recipient. If your recipient
syncs their Photos to iCloud, the Stecho carrier sits unencrypted in
Apple's storage (encrypted at rest by Apple, but with Apple holding
the keys unless Advanced Data Protection is enabled). This is not
Stecho-specific — it applies to anything sent over iMessage as an
image attachment.

### 4.7 Statistical analysis of the carrier *source*

If an adversary can compare a Stecho photo against the original
unmodified carrier, J-UNIWARD's content-adaptive cost map *itself*
becomes a side channel — they can see which coefficients were
modified and infer the embedding pattern. This requires possession
of both the original AND the Stecho version, which is uncommon but
not impossible (e.g., a user backs up the original to iCloud Photo
Library, then sends a Stecho-encoded version through iMessage; an
adversary with access to both copies has the source-target pair).

The mitigation is operational: **don't keep the unmodified source
photo if you've embedded a sensitive message into it.**

## 5. Adversary Models

For each adversary class, this section restates what Stecho defends
in concrete terms.

### 5.1 Casual snoop ("partner / parent / coworker peeking at your phone")

- Stecho photo is unrecognisable as anything other than a normal photo
  in Photos / Messages.
- They cannot read open-mode bodies because they don't have Stecho.
- They cannot read stealth-mode bodies because they don't have the
  password.
- They cannot tell from the JPEG file size or thumbnail that anything
  is hidden.

**Verdict: Stecho works as intended against this adversary.**

### 5.2 Casual stego-tool user ("knows F4 / J-UNIWARD decoders exist, runs them on phones they shouldn't")

- Open-mode JPEGs return `(SECO, body)` to any open-mode-aware
  decoder. They learn the content.
- Stealth-mode JPEGs without the password return `None`. The
  attacker cannot distinguish from "not a Stecho photo".
- They cannot tell from a Stecho JPEG alone whether it carries open,
  stealth, or no payload.

**Verdict: Stecho's stealth mode works as intended against this
adversary; open mode is exposed by design.**

### 5.3 Cellebrite-class digital forensics (border control, police)

These tools typically operate on unlocked devices and extract:

- Keychain contents (including Stecho's password if the user is
  signed in).
- Photos library (including any Stecho carriers sitting there).
- Network captures (iMessage attachments, decryptable with iCloud
  account credentials in many jurisdictions).

If the device is unlocked AND the operator has time to extract:

- Open-mode JPEGs: trivially decodable (anyone with Stecho can).
- Stealth-mode JPEGs: decodable because the password is in Keychain.
- Past messages: retroactively decryptable (no forward secrecy).

**Verdict: Stecho does not survive Cellebrite-class extraction of an
unlocked device.** The biometric lock and Keychain accessibility
attributes raise the friction for an *intermittent* extraction
attempt (no biometric → no Keychain → no password → no decode), but
do not survive a sophisticated operator with time.

### 5.4 State-level signal intelligence with stegoanalysis CNN

- Stecho photos in transit may be flagged by a J-UNIWARD-trained
  CNN classifier with 70-78% accuracy at `α = 0.08`. This is
  per-image; with N photos, an adversary needing a high-confidence
  flag can aggregate to lower false positive rates at the cost of
  hit rate.
- Once flagged, content remains AES-GCM-protected. The classifier
  alone yields no plaintext.
- However, "this JPEG is statistically anomalous" can be a basis
  for further targeted attention (request iCloud unlocking,
  border-control escalation, physical surveillance).

**Verdict: Stecho's content confidentiality survives even
classifier-flagged messages, but the metadata "this looks like a
Stecho photo" does not.** Users who model this threat — journalists
under targeted surveillance, sources in restrictive states — should
not rely on Stecho's *concealment* property; they should rely on
its *content protection* property and assume the classifier may
flag.

### 5.5 Targeted on-device malware (Pegasus-class)

Any spyware with read access to the user's iMessage data, Photos
library, or Stecho process memory defeats Stecho by definition. The
spyware sees the decoded plaintext on the user's screen, or the
decoded audio in the speaker buffer, or the password as it enters
Stecho's input field via the OS keyboard.

**Verdict: Stecho does not defend against device-level compromise.
No application can.** If you're in this threat model, the iOS
device itself is no longer the right place for your sensitive
communication — switch to a hardware solution, an air-gapped
device, or a tradecraft-based channel (encrypted shortwave, dead
drops, etc.).

## 6. Specific Scenarios

### 6.1 Mission user: VPN keys to / from a restricted-network country

The original Stiger framing — and inherited by Stecho — is that
people in countries where Telegram / WhatsApp / Signal are blocked
but iMessage remains accessible can use Stecho to receive things
like VPN configuration data inside ordinary photos.

For this specific use case:

- The carrier looks like a normal photo. Border control / customs /
  workplace search will not identify it as a tool of interest.
- The body is AES-GCM-encrypted. Even if a casual reviewer suspects
  steganography and runs a decoder, they cannot read it without the
  password.
- The recipient must be on Pro (or use the Russian-language free-Pro
  gate per [`AGENTS.md`](AGENTS.md)) — open mode is publicly
  readable and not useful here.
- The password must be exchanged out-of-band (in person, via a
  trusted channel) — Stecho's pairing flow uses a QR-code-based
  ECDH exchange, which is fine when the two parties can briefly
  meet but does not survive a remote-only setup.

**Stecho works for this use case** against the realistic adversary
(automated content scanning of iMessage by the regime, manual review
of suspected photos at customs). It does NOT survive a targeted
attack with steganalysis CNN classifier OR with on-device malware.

### 6.2 Journalist sending sensitive voice notes to a source

- Voice content is AES-GCM-protected.
- Embedding rate is fixed and low (α = 1/12), giving moderate but
  not zero detectability against a CNN classifier.
- The source device's security is out of scope.
- iMessage attachment is the transit medium — if the source / target
  is on Android, iMessage downgrades to SMS / MMS which **does not
  preserve JPEG bytes** and Stecho fails. iMessage-to-iMessage only.

**Verdict: Stecho is appropriate for "content protection under
iMessage-to-iMessage delivery to a known-secure recipient", not
for "untraceable communication that survives forensic analysis".**
For the latter, use Signal with Sealed Sender + ephemeral messages,
or a dedicated tradecraft channel.

### 6.3 iMessage drops the JPEG attachment to MMS (SMS fallback)

If the recipient is offline / on Android / abroad on a non-iMessage
carrier, the message can downgrade to MMS. MMS aggressively
recompresses image attachments. **Stecho payload does not survive
MMS.** The decoder returns `None` for the recipient.

Stecho's UI must warn the user when iMessage is unavailable for the
target conversation. (The current implementation does not yet enforce
this — TODO during the rebuild.)

## 7. Open Questions / Known Unknowns

These are areas where Stecho does not yet have a defensible answer
and where the threat model may need to be updated as we measure
things:

- **CNN detection on real iPhone photos.** Academic numbers are for
  BOSSbase 512×512 monochrome. We have not formally measured against
  modern iPhone JPEG output. Real-world accuracy may be substantially
  lower (carrier out-of-distribution for the classifier) or higher
  (more textured carriers may give the embedder less hiding room).

- **iOS version sensitivity.** The iMessage transport invariant has
  been confirmed empirically on iPhone 15 Pro / iOS 26.4.2 (the
  canonical test device). Behaviour on older OS / older iPhones is
  not on file. See
  [`docs/experiment-jpeg-imessage-survival.md`](docs/experiment-jpeg-imessage-survival.md).

- **Low Quality Image Mode interaction.** iMessage has a setting to
  send images at reduced quality. Whether this triggers
  recompression on JPEG attachments is not measured.

- **Cellular vs Wi-Fi transit.** Low-bandwidth networks may invoke
  different attachment paths. Not measured.

- **HEIC vs JPEG attachment dispatch.** Modern iOS captures HEIC by
  default; Stecho explicitly re-encodes to JPEG before insertion.
  Whether iMessage might prefer the HEIC sibling representation in
  any path is not measured.

## 8. Reporting Issues

If you find a gap between what this document says Stecho defends and
what the implementation actually does, that's a bug — file an issue
in the public repository. If you find a real attack on the wire
format itself (cryptographic or steganographic), please disclose
responsibly: open a private security advisory before public
disclosure.

## 9. Glossary

| Term            | Definition                                                       |
|-----------------|------------------------------------------------------------------|
| AAD             | Additional Authenticated Data (input to AES-GCM, not encrypted but covered by the tag) |
| AES-256-GCM     | AES with Galois/Counter Mode, 256-bit keys, 16-byte tag         |
| `α` (embedding rate) | Message bits per non-zero AC coefficient — Stecho v1 fixes α=1/12 |
| bpac            | Bits per non-zero AC coefficient (alternate name for `α`)        |
| BOSSbase        | Standard academic test corpus of 512×512 grayscale photos        |
| Daubechies-8    | The 8-tap orthogonal wavelet used by J-UNIWARD's residual filter |
| Forward secrecy | Property that compromise of long-term keys does not retroactively decrypt past sessions |
| J-UNIWARD       | JPEG Universal Wavelet Relative Distortion (Holub-Fridrich 2014) |
| Open mode       | Stecho's free-tier framing — no encryption, publicly readable    |
| PBKDF2          | Password-Based Key Derivation Function 2 (RFC 8018)              |
| Stealth mode    | Stecho's Pro-tier framing — AES-GCM under password-derived key   |
| STC             | Syndrome-Trellis Codes (Filler-Judas-Fridrich 2011)              |
| Wet position    | Coefficient marked as unusable for embedding (DC, `\|c\| ≤ 1`, saturated block) |
