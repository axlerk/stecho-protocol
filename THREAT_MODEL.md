# Stecho — Threat Model

This document says what Stecho protects, what it does not, and what we
have measured. Read it before trusting the app with anything that
matters.

If the implementation does less than this document says, the
implementation is wrong: please open an issue. If this document says
more than a record backs, the document is wrong: please open an issue
too.

The byte-for-byte wire format and an independent reference decoder you
can run yourself are in [`spec/`](spec/README.md). The app writes
embedding layer v2 (since 2026-11-04) and no longer reads v1 carriers
(retired 2026-11-10); v1 is described in [§7](#7-history-layer-v1).

## TL;DR

**English.**

- A voice or text message is encrypted (AES-256-GCM, key from your
  password) and hidden in the DCT coefficients of an ordinary JPEG,
  which goes through iMessage as a normal photo.
- With a password, the content stays unreadable without it. Without a
  password (open mode) anyone with Stecho reads it.
- Stecho does not hide *that* a photo may carry a message: Messages
  labels the photo "From Stecho", and a statistical test can flag it;
  in our measurements, hardly at the default setting, easily at the
  largest one.
- A phone in someone else's hands defeats it: saved passwords, spyware,
  screenshots. A leaked password opens every past message under it.

**По-русски.**

- Голосовое или текстовое сообщение шифруется (AES-256-GCM, ключ из
  вашего пароля) и прячется в DCT-коэффициентах обычной JPEG-фотографии,
  которая уходит через iMessage как обычное фото.
- С паролем содержимое без него не прочитать. Без пароля (открытый
  режим) его прочитает любой, у кого есть Stecho.
- Stecho не скрывает *сам факт*, что в фото может быть сообщение:
  «Сообщения» подписывают фото «From Stecho», а статистический тест
  может его заметить: в наших замерах с трудом на настройке по
  умолчанию и легко на самой большой.
- Телефон в чужих руках сводит защиту на нет: сохранённые пароли,
  шпионская программа, скриншоты. Утёкший пароль открывает все прошлые
  сообщения под ним.

## 1. What Stecho does

Stecho hides a short voice note or a text inside a JPEG photo and sends
the photo through iMessage as an ordinary image attachment. The photo is
re-encoded first: scaled to the carrier size, cropped to whole 16 px
blocks, quantised by Stecho itself at quality 0.85 into Apple's sharing
colour profile, with a minimal EXIF block. The message bits go into the
non-zero AC coefficients of all three planes, placed by content-adaptive
costs (SI-UNIWARD) and syndrome-trellis codes, so that the changes land
where the photo hides them best
([`spec/juniward-layer.md`](spec/juniward-layer.md) §V2).

**The rate follows the message.** The layer has five rates, 0.025, 0.05,
0.1, 0.2 and 0.4 bits per non-zero AC coefficient (§V2.5). The encoder
takes the smallest one that holds the message, up to the ceiling of the
sender's preset: Hidden 0.1, Balanced 0.2 (the default), Long messages
0.4; the free tier gets one rate lower (§V2.5.3). The rate is not written
anywhere; the decoder tries all five in order. On the median of the five
iPhone photos measured in the simulation, 0.2 holds about 18 s of 12 kbps
voice on a 2048 px carrier and about 34 s on a 3024 px one (§V2.10,
simulated counts, not a guarantee).

Two modes share the layer:

- **Open mode** ([`spec/open-v2.md`](spec/open-v2.md)), free, no
  password. The stream starts with the `SECO` magic, a version, a type
  and a length. Anyone with Stecho or a conforming decoder reads it. Not
  a privacy feature: it exists so the free tier has the same flow.
- **Stealth mode** ([`spec/stealth-v2.md`](spec/stealth-v2.md)), Pro,
  shared password. The body is wrapped in AES-256-GCM under a key derived
  from the password, and laid out in a password-derived order of the
  cover. No magic, no length in clear.

The composer sends stealth only when the chat has a password and
encryption is on; every other state sends open and says so
(`EncryptionState.swift`). Russian-language devices get Pro for free
(`RussianAudience.swift`); the reason is in [`AGENTS.md`](AGENTS.md).

**Transport.** The carrier is inserted as a plain attachment
(`MSConversation.insertAttachment`). Messages re-encodes any photo tagged
Display P3 before delivery, at about quality 0.75, which destroys the
payload; a file already in Apple's sharing profile, in sRGB or with no
profile goes through byte for byte. Measured 2026-11-02 over 39 sends
between an iPhone 12 mini (iOS 26.7.2) and an iPhone 15 Pro (iOS 27.2),
then 8 of 8 sends of the fixed carrier in both directions, text and voice
([`docs/experiment-device-transport.md`](docs/experiment-device-transport.md)).
This is observed behaviour, not a promise by Apple; see §4.5.

This document covers the content-and-transport layer. The app's UI,
paywall and biometrics are covered in the implementation and in
[`AGENTS.md`](AGENTS.md), and appear here only where they touch the
cryptographic story.

## 2. What stealth mode protects

### 2.1 The content

The body is encrypted with AES-256-GCM before embedding. The key is
PBKDF2-HMAC-SHA256 of the password with 600 000 iterations and a random
16-byte salt per message (stealth-v2 §5). Without the password the
stream is random bytes: a random salt, a random nonce, ciphertext, a
tag. We claim nothing beyond the published strength of these primitives.

**The password is the whole defence.** The permutation key is PBKDF2 of
the password with a fixed salt (stealth-v2 §2.1), so a prepared attacker
computes one table of permutation keys for every Stecho user once, and
then pays one PBKDF2 run per message, rate and guess for the AES key
(stealth-v2 §10). PBKDF2 is cheap on graphics cards. A short or guessable
password turns a recorded photo into a readable one.

### 2.2 The content's integrity

The GCM tag covers the ciphertext and the salt and nonce. Any change to
the embedded stream fails the check and the decoder returns nothing. A
wrong password and a tampered carrier look the same to the user.

### 2.3 No fingerprint in the stream

A stealth stream holds no magic, no version and no length outside the
encrypted region; it starts with the random salt. Someone who reads the
coefficients in Stecho's order finds no byte pattern to search for, and
someone who tries a password learns "no message" at the same cost for
"wrong password" and "not a Stecho photo" (stealth-v2 §4, §7). This is
protection against decoders, not against statistics: §4.1.

## 3. What open mode protects

Almost nothing. The photo looks like a photo in Photos and Messages, so
a casual look reveals nothing, but anyone with Stecho or an open-mode
decoder reads the body in a moment, and the `SECO` magic marks the
stream as Stecho's on purpose. Use stealth mode when the content matters.

## 4. What Stecho does not protect

### 4.1 That a photo carries a message

A statistical test can tell a photo with a message from one without,
without recovering the content. How well depends on the rate, the photo
and the test.

**What the app writes: layer v2 with the hybrid cover** (from
2026-11-08). The message is written into the DCT coefficients of
Apple's own JPEG encode of the picture: the file ImageIO writes for the
same pixels at quality 0.85 with Apple's sharing colour profile. Without
a message that file is byte-identical to Apple's encode (checked on 88
test carriers from 80 sources, and in a unit test), so Stecho's encoder
adds no statistical mark of its own; the file-level signs in §4.3
(quality-0.85 tables, minimal EXIF, 16 px sides) still apply. What a
detector can look for is the embedding itself, and how visible that is
depends on how much is embedded. The rate is the smallest of five rungs
that holds the message, capped by the sender's preset: Hidden at rung 3,
Balanced (the default) at rung 4, Long at rung 5. Free users send one
rung lower, in open mode, which anyone with Stecho can read anyway.

> **What we have measured** (2026-11-07 to 09,
> [`docs/experiment-steganalysis-v2-si.md`](docs/experiment-steganalysis-v2-si.md),
> rounds 3 to 5). Conditions:
> - Carriers from the app's own engine (STCv2, stealth-v2, quality
>   0.85), emitted in the simulator. Each is scored against Apple's
>   encode of the same picture: the ordinary photo a warden would see
>   instead.
> - Real photos, all the owner's own. Rounds 3 and 4: 8 iPhone 15 Pro
>   photos, as 24 crops at 2048 px and as the 8 originals at 2048 and
>   3024 px (the presets' size). Round 5: 59 originals from two phones
>   (55 iPhone 15 Pro, 4 iPhone 12 mini) at 3024 px.
> - Detectors: a DCTR feature + FLD ensemble (trained 5-fold by photo on
>   72 sources and scored on the round-4 originals; in round 5 trained
>   5-fold by photo on the 59 photos themselves) and the untrained
>   calibration test `beta_Y` (the F5-attack family).
>
> AUC on real photos (0.5 = chance, 1.0 = always caught), lowest to
> highest across the corpora:
>
> | Rung (preset ceiling) | DCTR + FLD | untrained `beta_Y` |
> |---|---|---|
> | 1–3 (Hidden; short messages under any preset) | 0.49–0.54 | 0.52–0.67 |
> | 4 (Balanced) | 0.52–0.55 | 0.50–0.69 |
> | 5 (Long) | 0.59–0.71 | 0.98–1.00 |
>
>
> On the largest set, round 5's 59 photos with the detector trained on
> them: DCTR 0.52 through rung 3, 0.55 at rung 4 and 0.68 at rung 5; the
> untrained test 0.53–0.57 through rung 4 and 0.98 at rung 5.
>
> For comparison, plain J-UNIWARD written into the same Apple file is
> caught by the untrained test at rung 3 (0.74–0.84) and at rung 4
> (0.97–1.00). Photos that are already a JPEG at the carrier size (24
> made from the same photos) gave DCTR 0.51–0.53 through rung 4 and 0.62
> at rung 5; the untrained test does not work on them, for covers and
> carriers alike. Smooth images are much easier: at rung 4 the untrained
> test scored 0.98 on wallpaper crops and 0.84 on synthetic images.

**A Long message can be told from an ordinary photo by a published
statistical test with no training**, without recovering the content.
The test is the 2002 F5 calibration attack, a few dozen lines of numpy,
so anyone who can run a published attack on a photo has it. The app
says so when a message passes the Balanced line. At the Hidden and
Balanced ceilings the trained detector stays at chance on these photos
(at most 0.55), and the untrained test reaches at most 0.69 on the
8-photo sets and 0.57 on the 59-photo set. That is not a claim of
undetectability:

- The corpus is still modest: the owner's own photos, 8 in rounds 3 and
  4 and 59 from two iPhones in round 5, all taken by one person. A
  detector trained on many people's phone photos may do better.
- Anyone who also holds the original photo can probably rebuild the
  cover (inferred: Apple's encode of the same pixels was identical on
  every source measured) and then see every changed coefficient (§4.8).
- v2 builds from 2026-11-04 to 2026-11-08 wrote Stecho's own JPEG encode
  instead of Apple's. A trained detector separates that file from
  Apple's at AUC 0.76–0.83, and the untrained test at 0.77–0.87 on
  real photos, with or without a message.

Not measured, and therefore not claimed:

- a network trained on Stecho carriers. Four published, pretrained
  steganalysis networks did no better than the detectors above on
  simulated v2 carriers on 2026-11-04
  ([`docs/experiment-steganalysis-cnn.md`](docs/experiment-steganalysis-cnn.md)),
  which says little about one trained for the purpose;
- byte identity through iMessage for a hybrid carrier. One hybrid voice
  message went from the iPhone 12 mini to the 15 Pro on 2026-11-08 and
  the delivered file decoded at the rung it was written with; the sent
  file was not captured for comparison. A sharing-profile carrier
  arrives byte for byte (§4.5), so the coefficients should be the same
  ones;
- the 2048 px setting from a camera HEIC on a phone, where ImageIO rounds
  differently; the 3024 px presets were measured as the phones see them.

Open and stealth carriers at the same rate use the same layer, costs and
rate, so they should be equally detectable (inferred, open-v2 §8). A
positive test exposes the fact of hiding, not the content; the content
stays under AES-GCM.

### 4.2 The size of the message

A message fills one of the five rates, so whoever can read the stream
learns the message size to within 2×: anyone in open mode, the password
holder in stealth mode. Without the password the rate is not readable,
only estimable from how many coefficients changed; that estimate has not
been measured (stealth-v2 §10). A text and a minute of voice on the same
photo do change different numbers of coefficients.

### 4.3 The file itself

Without any steganalysis, the file says an app made it:

- Its quantisation tables are ImageIO's for quality 0.85 (luma row 0
  `1 1 1 2 3 4 6 7`). A photo that Messages re-encoded has Apple's
  quality-0.75 tables (`2 2 2 3 5 6 8 10`), so a reviewer who compares
  received photos' tables can tell a Stecho carrier from an ordinary
  received photo (inferred from the measured tables, 2026-11-03,
  [`docs/experiment-steganalysis.md`](docs/experiment-steganalysis.md)
  §1; not tested against a reviewer).
- Its EXIF is minimal: colour space and pixel size, no camera, no
  location (same record).
- Its sides are multiples of 16 px: a 4:3 photo at 3024 px leaves as
  3024×2256, not 3024×2268 (`CarrierReencoder.swift`).

None of this says what is inside, or that anything is. File size says
little in v2: the embedding changes the file by at most 0.3 % on the
iPhone photos, and a cover-free size score scored at most 0.567 there
(simulated, 2026-11-03, the v2 record §2 and §3). Two carriers from
the same photo with different messages still differ in size; the encoder
does not pad the file to a fixed byte count.

### 4.4 "From Stecho" in Messages

A photo the extension inserts shows an item naming the app in Messages'
long-press menu: "Desde Stecho" on the receiving iPhone 15 Pro with a
Spanish UI, "From Stecho" in the simulator. Anyone holding either phone
sees which app sent the photo, even after a re-encode destroyed the
payload (recorded 2026-11-01,
[`docs/experiment-device-transport.md`](docs/experiment-device-transport.md),
Finding 3). The Pro setting Copy instead of send puts the carrier on the
local pasteboard (`localOnly`, so Universal Clipboard does not relay it)
and the user pastes it themselves; whether a pasted photo shows no app
item has not been recorded.

### 4.5 Transport

Stecho needs the JPEG to arrive with its coefficients untouched. Messages
re-encodes Display P3 photos (§1), which is why the carrier is written in
the sharing profile; which property of the profile Messages checks was
not separated, and the rule is measured on one pair of phones and Apple
IDs, iOS 26.7.2 and 27.2, over Wi-Fi. If Apple changes the pipeline, the
payload is destroyed and the reveal says there is no message. Nothing in
the wire format can prevent that; the mitigations are to watch iOS
releases and keep the bench matrix current.

**MMS.** If the recipient is on Android, offline or outside iMessage, the
message can fall back to MMS, which re-encodes image attachments
(platform behaviour as recalled; not measured, the test phone has no
SIM). A message that goes out as MMS arrives without its payload. Stecho
works iMessage to iMessage only, and does not yet warn when iMessage is
unavailable for the conversation.

### 4.6 Your phone

- **Saved passwords.** They sit in one Keychain item with
  `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`
  (`KeychainHelper.swift`). That is good hygiene, not protection from
  someone with forensic tools and an unlocked phone. Each chat has its
  own password, so one coerced or copied password opens one chat; a copy
  of the item opens every chat whose password is saved. Saving is a
  choice each time ("Save for this chat"); off keeps the password off
  the phone at the cost of typing it on every reveal.
- **The saved list is readable.** The item holds how many passwords are
  saved, when, which chats they are bound to (device-local participant
  identifiers, no names) and any name the user gave. With the Face ID
  lock off (the default), anyone holding the unlocked phone opens every
  chat with a saved password in one drag. The chat bindings are lost
  when the app is installed again (measured in Stiger on iOS 27.2 and
  26.7.2, not re-measured in Stecho,
  [`docs/experiment-participant-ids.md`](docs/experiment-participant-ids.md));
  a reveal then makes one automatic attempt with the chat's password and
  offers the other saved ones in a menu, one attempt per pick
  ([`docs/chat-passwords.md`](docs/chat-passwords.md)). A wrong stealth
  attempt costs a whole decode, up to five rates and six PBKDF2 runs
  (stealth-v2 §9).
- **Keyboard, drafts, screenshots.** Stecho keeps no long-lived
  plaintext draft, but cannot stop the keyboard from caching what you
  type, the recipient from screenshotting, or VoiceOver from speaking
  the text aloud.
- **Coercion.** Someone who can make you unlock the phone gets what the
  phone has. The biometric lock adds friction, not protection.
- **Spyware.** Anything that reads the screen, the speaker buffer or the
  keyboard sees the message in the clear. No app can defend against
  that; if this is your situation, the phone is the wrong place for the
  conversation.

### 4.7 The recipient's phone

Everything in §4.6 applies to the other end. A careless or malicious
recipient is out of scope. If their Photos sync to iCloud, the carrier
sits in Apple's storage under Apple's keys unless Advanced Data
Protection is on; that is true of any photo sent over iMessage.

### 4.8 The original photo

Someone who has both the original and the Stecho version sees exactly
which coefficients changed. That pair exists whenever the original stays
in the Photos library and the carrier goes out through iMessage. If the
message matters, do not keep the original.

### 4.9 No forward secrecy

A password that leaks today decrypts every past message under it.
Forward secrecy would need a key exchange or per-message state that a
photo attachment does not carry, so this is by design. Rotate passwords
if you suspect a leak; the pairing flow (`SecurePairingExchange.swift`,
two QR codes, ECDH P-256) carries a new password but gives the old
messages nothing.

## 5. Who sees what

| Who | What they can see | What stays protected |
|---|---|---|
| **A casual snoop** with your phone in hand (partner, parent, coworker) | A normal-looking photo; "From Stecho" if they long-press it in Messages (§4.4); every chat with a saved password, if the Face ID lock is off (§4.6) | Open and stealth content without the phone; stealth content without the password or a saved one |
| **Someone with a published steganalysis test** (a few dozen lines of code, no training) | Open-mode content, in full. In our measurements, hardly anything at Hidden or Balanced on iPhone photos, a clear flag at Long messages and on smooth images (§4.1); the message size to within 2× in open mode (§4.2); the file's tables, EXIF and 16 px sides (§4.3) | Stealth content. A flag is a reason to look closer, not a decrypt |
| **Forensic extraction of an unlocked phone** (someone with the tools and time: border control, police) | Saved passwords from the Keychain, so every chat with a saved password, past messages included (§4.6, §4.9); the Photos library; which photos came from Stecho (§4.4) | Chats whose password was never saved, as long as the password is strong (§2.1) |
| **Spyware on the phone** | The decoded text on screen, the voice in the speaker buffer, the password as it is typed | Nothing (§4.6) |

Content protection under iMessage-to-iMessage delivery to a recipient you
trust is what Stecho is for. Communication that must survive a forensic
look at the phone, or an examiner who flags statistically odd photos, is
not.

## 6. Open questions

- **A larger corpus and a trained network.** The figures in §4.1 come
  from the shipping encoder with real codes, but on 8 real photos and
  with classical detectors. No network has been trained on Stecho
  carriers, and many more phone photos may move the numbers.
- **A test written for v2.** The calibration tests were built for v1's
  shrinkage and are applied to v2 with a learned sign; a test of v2's
  `|c| = 1 ↔ 2` balance has not been written.
- **Sources already JPEG at carrier size** (§4.1).
- **iOS version sensitivity.** The transport rule is measured on
  iOS 26.7.2 and 27.2 only, two phones, one pair of Apple IDs, Wi-Fi
  only; iPad and the Mac as senders, cellular, and Messages' "Send Low
  Quality Photo Previews" switched on are not on file.
- **The pasted photo** (§4.4): whether it carries an app item.
- **MMS** (§4.5): not testable here.

## 7. History: layer v1

The app wrote layer v1 until 2026-11-04
([`spec/juniward-layer.md`](spec/juniward-layer.md) §1–§9,
[`spec/open-v1.md`](spec/open-v1.md),
[`spec/stealth-v1.md`](spec/stealth-v1.md)). Only one TestFlight build
(build 1) ever wrote it, and no App Store release contains it; on
2026-11-10 the app stopped reading v1 carriers too (they read as "no hidden
data"), and the spec marks v1 retired.
What was different, and what was measured on it:

- **A fixed rate.** v1 embedded 1/12 bit per AC slot, zeros included,
  and padded every message to the whole stream, so a 5-byte text and a
  minute of voice changed the same number of coefficients on a given
  photo (no length oracle through the rate). The price was a high load:
  0.64 bits per non-zero AC coefficient on wallpaper crops, 0.17 on
  synthetic images, 0.34 on iPhone photos; about 30 s of 12 kbps voice
  on every 2048 px send. Zeros were "wet" but got changed anyway on
  smooth sources (20 % of changes on wallpaper crops), which grew the
  file (median +10 %, max +35 %).
- **Detected without training.** Measured 2026-11-02/03 on carriers from
  the real engine at the product settings, emitted in the simulator
  ([`docs/experiment-steganalysis.md`](docs/experiment-steganalysis.md)
  §3, §4, §7): a 2002 calibration test told v1 stealth carriers from
  covers at AUC 0.980 on 150 wallpaper and synthetic sources (0.997 at
  quality 0.75) and 1.000 on 5 iPhone 15 Pro photos; a DCTR feature
  ensemble at 0.972 and 0.937 (0.980 and 0.995 at 0.75). Filling only
  part of the stream would have left the test at 0.975 at 25 % and 0.836
  at 10 % on the iPhone photos. A cover-free size score separated
  wallpaper carriers at 0.767 and open-mode carriers on the iPhone
  photos at 0.984 (files grew 3 %); stealth carriers there shrank
  slightly (0.994 of the cover). Four pretrained networks did worse than
  the untrained test on v1: at best 0.727 on the iPhone photos
  ([`docs/experiment-steganalysis-cnn.md`](docs/experiment-steganalysis-cnn.md)).
- **Quality 0.75 would not have helped.** The same stream at 0.75
  carried 27–63 % more bits per non-zero AC on wallpapers and synthetic
  images and 19 % more on the iPhone photos (0.338 → 0.402), and
  detection went up, not down (calibration 0.980 → 0.997, DCTR
  0.972 → 0.980; on the iPhone photos DCTR 0.937 → 0.995).
- **Costs and order.** v1 computed chroma costs on a luma stand-in,
  always shrank `|c|`, and open-v1 walked the slots in identity order,
  which clustered the usable coefficients.

Earlier versions of this document quoted 70–78 % from the literature for
trained networks on J-UNIWARD at a comparable rate. That figure was
recalled, mixed a per-slot rate with a per-coefficient one, and is
withdrawn: measured and simulated numbers exist above.

## 8. Reporting issues

A gap between this document and the implementation is a bug: file an
issue in the public repository. A real attack on the wire format,
cryptographic or steganographic, deserves a private security advisory
before public disclosure.

## 9. Glossary

| Term | Definition |
|---|---|
| AAD | Additional Authenticated Data: input to AES-GCM, not encrypted but covered by the tag |
| AES-256-GCM | AES with Galois/Counter Mode, 256-bit keys, 16-byte tag |
| AUC | Area under the ROC curve of a detector: 0.5 is chance, 1.0 a perfect split |
| bpnzAC | Bits per non-zero AC coefficient: v2's rate unit |
| DCTR | A feature set for JPEG steganalysis, here with a linear-classifier ensemble |
| Forward secrecy | Compromise of a long-term key does not decrypt past sessions |
| J-UNIWARD | JPEG Universal Wavelet Relative Distortion (Holub-Fridrich 2014): the cost of changing each coefficient |
| PBKDF2 | Password-Based Key Derivation Function 2 (RFC 8018) |
| Rate, rung | One of the five v2 rates; the stream size at that rate |
| SI-UNIWARD | Side-informed J-UNIWARD: costs scaled by the quantiser's rounding error |
| STC | Syndrome-Trellis Codes (Filler-Judas-Fridrich 2011): which coefficients change |
| Stealth / open mode | With a password and AES-GCM / without a password, publicly readable |
