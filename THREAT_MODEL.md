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
carrier). **What it does not:** hide the *fact* that a photo carries
a message. A published statistical test with no training tells today's
(v1) stealth carriers from ordinary photos at AUC 0.98-1.00 (measured on
simulator carriers, real iPhone photos included, §4.1), without
recovering the message; Messages also labels photos sent from the
extension "From Stecho" (§4.8). A compromised device, a forensic
Keychain dump, screenshots, or iMessage recompression all defeat or
destroy the payload. **Open mode** (no password) is publicly readable by anyone
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
*сам факт* того, что в фото что-то спрятано. Опубликованный
статистический тест без всякого обучения отличает нынешние (v1)
stealth-фото от обычных с AUC 0.98-1.00 (измерено на носителях из
симулятора, включая реальные фото с iPhone, §4.1), не читая
сообщения; кроме того, Messages подписывает фото, отправленные из
расширения, как «From Stecho» (§4.8). Компрометация устройства,
форензик-дамп Keychain, скриншоты и пережатие iMessage — всё это либо
обходит, либо уничтожает payload. **Открытый режим** (без пароля) читается любым, у
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
> image attachments (`MSConversation.insertAttachment`), encoded with
> Apple's "Apple Wide Color Sharing Profile" (or plain sRGB when the photo
> has no colours outside sRGB). iMessage re-encodes any
> photo tagged Display P3 before delivery, which destroys the payload;
> a carrier already in the sharing profile goes through byte for byte.
> `MSSticker` objects and `MSMessage` layouts are re-encoded regardless.
> This is **observed platform behaviour, not a security guarantee**;
> the recompression failure mode is covered in §4.3 below. See
> [`docs/experiment-device-transport.md`](docs/experiment-device-transport.md)
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
predictable regions. This defeats the pairs-of-values chi-square test
(AUC 0.50-0.53 on every carrier measured). It does **not** defeat
calibration-based tests at v1's rate: the stock F5 calibration attack
scores AUC 0.960 and an adapted one 0.980 on 150 wallpaper and synthetic
sources, and both score 1.000 on 5 real iPhone photos (2026-11-03,
[`docs/experiment-steganalysis.md`](docs/experiment-steganalysis.md) §3 and §7). The cause is the full-stream rate, not the cost
function; see §4.1.

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

### 4.1 Steganalysis: detecting that a photo carries a message

J-UNIWARD's content-adaptive distortion is the academic state of the
art for JPEG embedding, but it is not undetectable. Modern detectors
(SRNet, GBRAS-Net, Yedroudj-Net) trained on J-UNIWARD-modified
JPEGs at `α = 0.08` detect with accuracy roughly 70-78% on standard
test corpora (BOSSbase, ALASKA II). These figures are recalled from
the academic literature and have not been independently measured by
Stecho.

**An adversary who runs a published statistical test can tell a v1
Stecho photo from an ordinary photo without recovering the content.**
No CNN and no training are needed (measured below). Content
confidentiality (AES-GCM) is unaffected — even a positive
classification doesn't reveal what was hidden — but the *fact* of
hiding is exposed.

This capability is not limited to state-level agencies or academic
labs: the test is the 2002 F5 calibration attack, a few dozen lines of
numpy, so anyone who can run a published attack on a photo has it. What
Stecho does defeat is format-fingerprint detection (§2.3). Layer v2
([`docs/proposal-layer-v2.md`](docs/proposal-layer-v2.md)) is designed
to lower these numbers with a variable, capped rate; v1 is what ships
today, and nothing in this section is measured on v2.

> **What we have measured** (2026-11-03,
> [`docs/experiment-steganalysis.md`](docs/experiment-steganalysis.md)).
> Conditions:
> - v1 carriers from the real engine at the product settings (2048 px,
>   quality 0.85, full stream), emitted in the simulator, not sent.
> - 150 sources: 102 crops of 17 macOS wallpapers (one of them a camera
>   photo) and 48 synthetic images.
> - The cover is the same source re-encoded without a payload.
>
> Stealth carrier vs cover:
> - An untrained calibration test (F5-attack family): AUC 0.980 (0.997 at
>   quality 0.75).
> - DCTR features + FLD ensemble, 5-fold by source: AUC 0.972, P_E 0.074
>   (0.980 / 0.090 at 0.75).
>
> The embedding load is 0.64 bits per non-zero AC coefficient on the
> wallpaper crops and 0.17 on the synthetic images.
>
> **Real iPhone photos** (2026-11-03, same doc §7). Conditions as above,
> on 5 everyday iPhone 15 Pro photos without people (full frame as
> HEIC + 9 crops each, 50 sources, 5 independent scenes); DCTR trained on
> the 150 sources above plus the other 4 photos. Stealth carrier vs cover:
> - The untrained calibration test: AUC 1.000 (1.000 at quality 0.75).
> - DCTR + FLD: AUC 0.937 (0.995 at 0.75).
> - The load is 0.34 bits per non-zero AC coefficient; almost no zero
>   coefficients are forced (0.2 % of changes).
> - If the stream were only partly filled (v1 always fills all of it,
>   about 30 s of voice at 12 kbps), the untrained test would still give
>   0.975 at 25 % (about 7.5 s) and 0.836 at 10 % (about 3 s); across all
>   three planes, 1.000 and 0.874.
>
> No CNN was measured. The literature's 70-78 % at the top of this
> section is for trained CNNs on academic corpora; it is neither an
> upper bound nor a forecast for Stecho. On v1 carriers an untrained
> test already scores higher.

### 4.2 Side channels on the user's device

A compromised device defeats Stecho in many ways the wire format
cannot help with:

- **Keychain dump.** Stecho's saved passwords are stored in one iOS
  Keychain item with `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`.
  This is good hygiene but does not survive a Cellebrite-class forensic
  extraction of an unlocked device. Once a password is dumped,
  every prior message under that password is decrypted retroactively.
  Each chat has its own password, so one dumped or coerced password
  opens one chat's messages, not every correspondent's; a dump of the
  whole item opens every chat whose password is saved. See §5 below.

- **The saved-password list is on-device metadata.** The same Keychain
  item holds how many passwords are saved, when each was saved, which
  chats each is bound to (as device-local participant identifiers, with
  no names or addresses) and any name the user gave a password. A name
  is optional by design: a popup asks for it when a new password is
  about to be saved, and anyone who opens Stecho on the unlocked phone
  can read it. "Save for this chat" off keeps a password off the phone,
  at the cost of typing it on every reveal. Someone holding the
  unlocked phone with the Face ID lock off (the default) opens every
  chat whose password is saved with one drag. Stecho cannot say which
  chat a password belongs to, and the chat bindings are lost when the
  app is installed again (measured in Stiger on iOS 27.2 and 26.7.2 with
  developer installs, not re-measured in Stecho:
  [`docs/experiment-participant-ids.md`](docs/experiment-participant-ids.md));
  a reveal then makes one automatic attempt with the password bound to the
  chat, and the user picks any other saved password from a menu, one attempt
  per pick (a wrong stealth attempt costs a whole decode).

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
destroyed and decoders return `None`.

This has already happened once. Measured 2026-11-02 between an
iPhone 12 mini (iOS 26.7.2) and an iPhone 15 Pro (iOS 27.2), 39 real
sends: iMessage re-encodes every photo tagged with a Display P3
profile before any receiver gets it (at the sender's upload or on
Apple's servers), at roughly quality 0.75 into the "Apple Wide Color
Sharing Profile". The April 2026 F4 build, which had worked on
iOS 26.4.2, failed the same way. Photos with the sharing profile, an
sRGB profile, or (JPEG) no profile went through byte for byte.
Stecho's carriers are therefore encoded with
`kCGImageDestinationOptimizeColorForSharing`, which yields the sharing
profile for wide-gamut photos and sRGB otherwise; with that carrier 8
of 8 sends survived (the carriers' profile was recorded for the Sonoma
sends, which carried the sharing profile, not for the repeats; an sRGB
JPEG was measured passing only as a pasted file), in both directions, text and voice, on four source
photos. Which property of the profile Messages checks (its name, its
bytes, or a wide-gamut flag) was not separated. See
[`docs/experiment-device-transport.md`](docs/experiment-device-transport.md)
for the full matrix.

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
information from the size delta.

Without the source, size still says something. A cover-free score
(the file's size against a calibrated re-compression of itself)
separates carriers from re-encoded photos (2026-11-03, simulator
carriers, [`docs/experiment-steganalysis.md`](docs/experiment-steganalysis.md) §2 and §7):
- v1 stealth on wallpaper crops: files grow (median +10 %, max +35 %)
  because zero coefficients are forced to ±1; AUC 0.767.
- v1 stealth on 5 real iPhone photos: files shrink slightly (median
  0.994 of the cover); AUC 0.81 for a score that knows that sign.
- Open mode on the real photos: files grow 3 %; AUC 0.984.
This is a "this JPEG is not a plain re-encode" signal, not a content
oracle.

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

### 4.8 "From Stecho" in Messages

A photo the extension inserts into a conversation
(`MSConversation.insertAttachment`) shows an item naming the app in
Messages' long-press menu: "Desde Stecho" on the receiving iPhone 15
Pro with a Spanish UI, "From Stecho" in the simulator. Anyone holding
either phone can see which app sent the photo, even after
recompression destroyed the payload (recorded 2026-11-01,
[`docs/experiment-device-transport.md`](docs/experiment-device-transport.md),
Finding 3). The Pro clipboard-send setting copies the carrier to the
local pasteboard instead of inserting it, so the user pastes it
themselves; whether a pasted photo shows no app item has not been
recorded.

## 5. Adversary Models

For each adversary class, this section restates what Stecho defends
in concrete terms.

### 5.1 Casual snoop ("partner / parent / coworker peeking at your phone")

- The photo looks like a normal photo in Photos / Messages, but a
  photo sent from the extension carries a "From Stecho" item in
  Messages' long-press menu (§4.8).
- They cannot read open-mode bodies because they don't have Stecho.
- They cannot read stealth-mode bodies because they don't have the
  password.
- Nothing is visible in the thumbnail. File size is not readable by
  eye, but a computed size score separates carriers (§4.5).

**Verdict: content is protected against this adversary; concealment
holds only if they don't long-press a photo sent from the extension.**

### 5.2 Casual stego-tool user ("knows F4 / J-UNIWARD decoders exist, runs them on phones they shouldn't")

- Open-mode JPEGs return `(SECO, body)` to any open-mode-aware
  decoder. They learn the content.
- Stealth-mode JPEGs without the password return `None`, so a
  decoder alone cannot distinguish them from "not a Stecho photo".
- A published steganalysis attack can. The stock F5 calibration
  attack separates v1 stealth carriers from re-encoded photos
  at AUC 0.960 on 150 wallpaper and synthetic sources and 1.000 on 5
  real iPhone photos (2026-11-03, simulator carriers,
  [`docs/experiment-steganalysis.md`](docs/experiment-steganalysis.md) §3 and §7).

**Verdict: stealth mode protects the content against this adversary
but not the fact that a message is hidden; open mode is exposed by
design.**

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
- Which photos came from Stecho: visible in Messages (§4.8).

**Verdict: Stecho does not survive Cellebrite-class extraction of an
unlocked device.** The biometric lock and Keychain accessibility
attributes raise the friction for an *intermittent* extraction
attempt (no biometric → no Keychain → no password → no decode), but
do not survive a sophisticated operator with time.

### 5.4 State-level signal intelligence with stegoanalysis CNN

- Stecho photos in transit can be flagged. Measured on v1 stealth
  carriers (2026-11-03, simulator, [`docs/experiment-steganalysis.md`](docs/experiment-steganalysis.md)): an untrained calibration
  test at AUC 0.980 (150 wallpaper and synthetic sources) and 1.000 (5
  real iPhone photos); a trained DCTR feature ensemble at 0.972 and
  0.937. A CNN has not been measured. This is per-image; with N photos,
  an adversary needing a high-confidence flag can aggregate to lower
  false positive rates at the cost of hit rate.
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

- The carrier looks like a normal photo, but a reviewer who
  long-presses it in Messages sees "From Stecho" if it was sent from
  the extension (§4.8), and anyone who runs a steganalysis test on it
  can flag it (§4.1).
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

**Stecho protects the content in this use case**: a reviewer who
suspects the photo still cannot read it without the password. It does
not hide that a message is there from automated scanning that runs a
steganalysis test, from a reviewer who sees the "From Stecho" item, or
from on-device malware.

### 6.2 Journalist sending sensitive voice notes to a source

- Voice content is AES-GCM-protected.
- Embedding rate is fixed (α = 1/12, full stream on every send), and
  at that rate an untrained statistical test detects v1 carriers at
  AUC 0.98-1.00 (§4.1).
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

- **CNN detection.** Untrained tests and a DCTR feature ensemble have
  been measured on v1 carriers, including 5 real iPhone 15 Pro photos
  (§4.1). A CNN has not: pretrained candidates are being checked for
  licence and fit. Five photos from one phone are a small sample, and
  no carrier in these measurements went through iMessage.

- **iOS version sensitivity.** The transport rule above (§4.3) is
  measured on iOS 26.7.2 and iOS 27.2 only, two devices, one pair of
  Apple IDs. Older OS versions, iPad and macOS as a sender are not on
  file. When Apple started re-encoding Display P3 photos is not
  known. See
  [`docs/experiment-device-transport.md`](docs/experiment-device-transport.md).

- **Quantization tables as a marker on the receiver.** An ordinary
  Display P3 photo arrives re-encoded by Apple (luma DQT row 0
  `2 2 2 3 5 6 8 10`, ~quality 0.75); a Stecho carrier arrives as sent,
  with quality-0.85 tables (`1 1 1 2 3 4 6 7`) under the same sharing
  profile. A reviewer who compares received photos' tables could tell
  them apart without steganalysis (inferred from the measured tables,
  not tested against a reviewer). Encoding carriers at 0.75 would close
  most of the gap (iOS ImageIO at 0.75 still differs from Apple's
  re-encode in 2 of 64 chroma entries, measured) at a cost in image
  quality (not measured) and in embedding headroom. The headroom was
  measured 2026-11-03 on simulator carriers
  ([`docs/experiment-steganalysis.md`](docs/experiment-steganalysis.md)):
  - The same stream at 0.75 carries 27-63 % more bits per non-zero AC
    coefficient on wallpapers and synthetic images, and 19 % more on 5
    real iPhone 15 Pro photos (0.338 → 0.402).
  - At v1's full-stream rate that makes the carrier easier to detect,
    not harder: calibration AUC 0.980 → 0.997, DCTR 0.972 → 0.980. On
    the real photos calibration is 1.000 at both qualities and DCTR goes
    0.937 → 0.995.

- **Low-quality photo previews setting.** Messages' "Send Low Quality
  Photo Previews" was off on both phones in every measured send; its
  effect when on is not measured.

- **Cellular vs Wi-Fi transit.** Low-bandwidth networks may invoke
  different attachment paths. Only Wi-Fi was measured (no SIM in the
  test phone).

- **HEIC vs JPEG attachment dispatch.** Stecho re-encodes every
  source to JPEG before insertion; a pasted HEIC was itself changed by
  Messages in transit.

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
