# Stecho — Support

## What is Stecho?

Stecho is an iOS app and iMessage extension that lets you hide a
secret message — a voice note, a text or a location — inside an
ordinary photo. The recipient sees a normal photo until they reveal it
in Stecho. A free secret is hidden but not encrypted: anyone with
Stecho can read it. With Stecho Pro you can lock it with a password
that you and the recipient share; to read a locked secret, the
recipient needs Stecho Pro and that password too.

## Quick start

1. Install Stecho from the App Store.
2. Open Messages → tap the apps drawer → choose Stecho.
3. Pick a photo: **Camera**, **Photos** or **Clipboard**.
4. Choose **Voice** and record a voice note, or **Text** and type a
   message. Tap **Add**, then send the photo as usual.
5. (Optional, Pro) Turn on encryption in Stecho's settings. From then
   on the screen where you record or type has a password field: type
   a password you and your partner already know, or agree a new one
   face to face with **Pair in Person** in settings. Your partner
   needs Pro as well to read it.
6. To read it, the recipient opens Stecho in Messages, touches and
   holds the photo in the conversation, and drags it into the Stecho
   panel.

For a deeper walkthrough of the cryptography, the wire format, and an
independent reference decoder in Python, see
<https://github.com/axlerk/stecho-protocol>.

## Frequently asked questions

**Q: Does Stecho have my voice notes / text?**
No. Everything is computed on your device. Stecho has no servers and
no accounts.

**Q: What encryption does it use?**
AES-256-GCM with a key derived from your password via PBKDF2-SHA256
(600 000 iterations). Open mode (the free tier) hides the message but
does not encrypt it; encryption requires Stecho Pro.

**Q: Can someone tell a photo has a secret in it?**
Open mode (free) is meant for fun: anyone with Stecho — or the
public reference decoder — can read it. Stealth mode (Pro, with a
password) carries no fixed marker for a scanner to look for, and
without the password its content stays hidden. It does not hide that
the photo was modified: statistical steganalysis tools can flag it as
a likely carrier. The threat model in the repository above spells out
what is and is not protected.

**Q: Does the hidden message survive being sent?**
Over iMessage, in our tests, yes. Stecho needs the photo to arrive
exactly as it left, so it saves every photo the way the iPhone itself
shares photos, and Messages has delivered those files unchanged. That
is what we observed, not a promise from Apple: if a future iOS changes
it, the photo arrives as an ordinary photo and Stecho finds no message
in it.

**Q: My recipient is on Android — does this still work?**
No. Stecho works iMessage to iMessage only. A photo that goes out as
SMS/MMS, or through another messenger, should be expected to arrive
without its hidden message.

**Q: I lost my password.**
We cannot recover it. Stecho keeps it only in this device's Keychain —
never on a server — and it leaves the device only if you share it with
a partner through QR pairing. Without it the secret is unrecoverable.

**Q: I'm in Russia and the App Store won't let me pay.**
All Pro features are unlocked automatically when your iPhone's primary
language is Russian — the first language in Settings → General →
Language & Region. Setting Russian only for Stecho (Settings → Stecho →
Language) does not unlock them.

## Contact

**hello@onegoodman.studio** — bugs, feature requests, security
issues. For security issues, please prefix the subject line with
`[SECURITY]`.

---

_Operated by Individual Entrepreneur Pavel Khudiakov (Tbilisi, Georgia)._
