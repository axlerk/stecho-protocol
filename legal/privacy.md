# Stecho — Privacy Policy

_Last updated: 20 November 2026_

Stecho is an iOS app and iMessage extension that hides a voice note,
a text or a location inside an ordinary photo using on-device
steganography and encryption. This document describes what data
Stecho does and does not collect.

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
| Passwords you choose to save, with the name you give each one and the chats it is for | iOS Keychain, this device only | Yes (Keychain) |
| App settings (encryption on/off, biometrics on/off, etc.) | App Group `UserDefaults` | No |
| Voice notes you record before sending | App Group container (transient — discarded once sent or composer dismissed) | No (iOS file protection only) |

Stecho does **not** keep its own copy of the photos you choose as
carriers — they come from your iOS Photos library or camera each time,
are converted to a steganographic JPEG in memory, and the result is
handed straight to iMessage. The original photo is unaffected.

Deleting the app removes everything in the App Group container. iOS
keeps Keychain items after an app is deleted; Stecho erases its saved
passwords the next time it is installed on this device. Until then they
stay in this device's Keychain, where no other app can read them.

## Outbound network requests

**None initiated by Stecho.** Stecho does not call any server, does
not refresh any catalog, does not phone home for any feature. The
encoded JPEG you send leaves the device only through Apple's iMessage
attachment pipeline, which is operated by Apple and outside Stecho's
control.

Stecho never uploads your voice notes, text, photos, location, or any
other user-generated content to any server.

## Location

Stecho requests location access only when you tap the location button
inside the iMessage extension. The coordinates are embedded as part of
the hidden message inside the photo you are about to send. If you deny
the permission, every other Stecho feature continues to work.

## Camera and Photos library

Stecho requests Photos library access only when you choose a photo
from your library as a carrier, and Camera access only when you choose
to take a fresh photo in the moment, or to scan a partner's QR code
when you pair a shared password. In every case the image is processed
on device. If you deny either permission, the other input sources
remain available.

## Microphone

Stecho requests microphone access only when you tap **Record** in the
iMessage extension to compose a voice note. The audio is encoded with
Opus, embedded into the chosen carrier JPEG on device, and the raw
recording is discarded once the message is sent.

## Face ID / Touch ID

Stecho uses biometric authentication only to gate its settings and
saved passwords and, if you turn it on, writing and reading secrets in
the iMessage extension. Authentication happens entirely
through Apple's `LocalAuthentication` framework; Stecho never sees
your biometric data.

## Purchases

In-app purchases (Stecho Pro monthly, yearly and lifetime, and Donate)
are processed by Apple via StoreKit. Stecho sees only
which of its products your Apple Account owns, as StoreKit reports it on
the device.
We do not receive your name, email, payment details, or App Store
account.

## What Stecho cannot protect against

The full list is in the threat model:
<https://github.com/axlerk/stecho-protocol/blob/main/THREAT_MODEL.md>.
Short version: with a password, Stecho protects what the message says
(AES-256-GCM, key derived with PBKDF2, 600 000 iterations). It does not
hide from statistical analysis that a photo may carry something, and it
cannot protect a phone that someone else can unlock or that runs
spyware.

## Children

Stecho is not directed at children under 13 and does not knowingly
collect data from them. Age rating: 4+.

## Changes to this policy

Updates will be published at this URL with a new "Last updated" date.

## Contact and data controller

Privacy questions, deletion requests, or anything else:

**Individual Entrepreneur Pavel Khudiakov** (Tbilisi, Georgia)
Email: hello@onegoodman.studio

The full registered address is on file with the Apple App Store and is
disclosed to regulators on request.
