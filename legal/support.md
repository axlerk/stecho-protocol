# Stecho — Support

## What is Stecho?

Stecho is an iOS app and iMessage extension that lets you hide a
short voice note or short text inside an ordinary JPEG photo. The
recipient sees a normal photo; if you have stealth mode enabled, you
and they share a password to reveal what's hidden inside.

## Quick start

1. Install Stecho from the App Store.
2. Open Messages → tap the apps drawer → choose Stecho.
3. Pick a photo (camera, library, or paste from clipboard).
4. Tap **Record** to record a voice note, or **Text** to type a short
   message.
5. (Optional but recommended) Turn on encryption in the main Stecho
   app and set a password you and your partner already know.
6. Tap send. The recipient taps the photo inside Messages and opens
   it with Stecho to play the voice note or read the text.

For a deeper walkthrough of the cryptography, the wire format, and an
independent Python reference decoder, see the spec in the project
repository.

## Frequently asked questions

**Q: Does Stecho have my voice notes / text?**
No. Everything is computed on your device. Stecho has no servers and
no accounts.

**Q: What encryption does it use?**
AES-256-GCM with a key derived from your password via PBKDF2-SHA256
(600 000 iterations). Open mode (the free tier) hides bytes inside the
photo's DCT coefficients but does not encrypt them; encryption
requires Stecho Pro.

**Q: Can someone tell a photo has a secret in it?**
The free **open mode** is steganographic but easy to detect with any
J-UNIWARD-aware tool — it is meant for fun, not adversarial use.
**Stealth mode** (Pro) hides the wire-format fingerprint (no magic
bytes, password-derived permutation) and encrypts the content, but
trained statistical steganalysis (J-UNIWARD-aware CNN classifiers)
can still detect *that some hiding happened* with non-trivial
accuracy. The *content* remains protected by AES-256-GCM. The full
threat model is published in the project's `THREAT_MODEL.md`.

**Q: Why JPEG photos and not stickers / HEIC / PNG?**
JPEG attachments survive iMessage's transport pipeline without being
recompressed end-to-end on current iOS versions. Stickers (`MSSticker`)
are re-encoded in transit and cannot carry hidden bytes. HEIC and PNG
also have transport-survival issues for our embedding rate. JPEG is
the only Apple-blessed image carrier that works for the product.

**Q: My recipient is on Android — does this still work?**
No. If iMessage downgrades to MMS/SMS for the conversation, the
attachment is re-compressed and the hidden payload is destroyed.
Stecho is iMessage-to-iMessage only.

**Q: I lost my password.**
We cannot recover it. The password never leaves your device, and
without it the hidden content is unrecoverable.

**Q: I'm in Russia and the App Store won't let me pay.**
All Pro features are unlocked automatically when your iPhone's primary
system language (iOS Settings → General → Language & Region → iPhone
Language) is set to Russian. The per-app language override (iOS
Settings → Stecho → Language) is intentionally **not** counted —
only the system-level language unlocks free Pro.

## Contact

**hello@onegoodman.studio** — bugs, feature requests, security
issues. For security issues, please prefix the subject line with
`[SECURITY]`.

---

_Operated by Individual Entrepreneur Pavel Khudiakov (Tbilisi, Georgia)._
