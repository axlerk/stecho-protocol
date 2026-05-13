# Stecho — Privacy Policy

_Last updated: 13 May 2026_

Stecho is an iOS app and iMessage extension that hides short voice
notes or short text inside ordinary JPEG photos using on-device
steganography (J-UNIWARD + STC) and AES-256-GCM encryption. This
document describes what data Stecho does and does not collect.

## TL;DR

- Stecho has **no servers**, **no accounts**, **no analytics**,
  **no advertising**, **no third-party tracking SDKs**.
- Everything you create — voice notes, text, carrier photos,
  passwords — stays on your device.
- Stecho makes **no outbound network requests** of its own.

## Data we collect

**None.** Stecho does not transmit any personal data to its developer
or to any third party for our own use.

## Data stored on your device

| What | Where | Encrypted at rest |
|---|---|---|
| Saved partner password (if you enable it) | iOS Keychain | Yes (Keychain) |
| App settings (encryption on/off, biometrics on/off, etc.) | App Group `UserDefaults` | No |
| Voice notes you record before sending | App Group container (transient — discarded once sent or composer dismissed) | No (iOS file protection only) |

Stecho does **not** keep its own copy of the photos you choose as
carriers — they come from your iOS Photos library or camera each time,
are converted to a steganographic JPEG in memory, and the result is
handed straight to iMessage. The original photo is unaffected.

Removing the app removes everything in the table above.

## Outbound network requests

**None initiated by Stecho.** Stecho does not call any server, does
not refresh any catalog, does not phone home for any feature. The
encoded JPEG you send leaves the device only through Apple's iMessage
attachment pipeline, which is operated by Apple and outside Stecho's
control.

Stecho never uploads your voice notes, text, photos, location, or any
other user-generated content to any server.

## Camera and Photos library

Stecho requests Photos library access only when you choose a photo
from your library as a carrier, and Camera access only when you choose
to take a fresh photo in the moment. In both cases the image is
processed on device. If you deny either permission, the other input
sources remain available.

## Microphone

Stecho requests microphone access only when you tap **Record** in the
iMessage extension to compose a voice note. The audio is encoded with
Opus, embedded into the chosen carrier JPEG on device, and the raw
recording is discarded once the message is sent.

## Face ID / Touch ID

Stecho uses biometric authentication only to gate access to settings
and saved passwords on your device. Authentication happens entirely
through Apple's `LocalAuthentication` framework; Stecho never sees
your biometric data.

## Purchases

In-app purchases (Stecho Pro monthly, yearly, lifetime, and Donate)
are processed by Apple via StoreKit. Stecho sees only an anonymous
entitlement flag indicating whether you have an active subscription.
We do not receive your name, email, payment details, or App Store
account.

## What Stecho cannot protect against

For completeness — and because Stecho is a security-adjacent tool —
the threat model is documented in detail at
<https://github.com/axlerk/Stecho/blob/main/THREAT_MODEL.md>. Short
version: Stecho protects message *content* (AES-256-GCM,
PBKDF2-600k); it does **not** claim to defeat trained
steganalysis-class adversaries who can detect that *some* hiding has
happened, nor does it survive device-level compromise (forensic
extraction, spyware).

## Children

Stecho is not directed at children under 13 and does not knowingly
collect data from them. Age rating: 12+.

## Changes to this policy

Updates will be published at this URL with a new "Last updated" date.

## Contact and data controller

Privacy questions, deletion requests, or anything else:

**Individual Entrepreneur Pavel Khudiakov** (Tbilisi, Georgia)
Email: hello@onegoodman.studio

The full registered address is on file with the Apple App Store and is
disclosed to regulators on request.
