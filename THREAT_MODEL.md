# Stecho — Threat Model

**Status:** TestFlight beta, not yet on the App Store. The text describes
the current code and says, in the place where it matters, where the latest
TestFlight build (2026-11-10) is behind it. Formats: embedding layer v2 with
`open-v2` and `stealth-v2`; the layer is a draft until the specification
freezes it. Last checked against the code on 2026-11-20.

This document says what Stecho protects, what it does not, and how we know.
Read it before you trust the app with anything that matters.

If the app does less than this document says, the app is wrong. If the
document says more than the code or a measurement backs, the document is
wrong. If a decoder written from the specification disagrees with the app,
one of the two has a bug. In each case, please tell us (§6).

The format, a reference decoder and test vectors are public:
<https://github.com/axlerk/stecho-protocol>. Every figure this document
relies on is in the text, with its sample size and date. The record named
beside it is where the run is written down; the records live in the app's
source repository, which is private. A dagger (†) marks what we have not
checked ourselves; §5 lists it all.

## TL;DR

**English.**

- A voice note or a text is encrypted and hidden in an ordinary JPEG photo,
  which goes through iMessage as a normal photo.
- With a password, nobody reads the message without it (AES-256-GCM, key
  from the password by PBKDF2-SHA256, 600 000 iterations). The password is
  the whole defence, so make it a long one.
- Stecho does not hide that a photo may carry a message. Messages shows
  which app sent the photo, and a statistical test can flag it: the longer
  the message, the easier. A message at the Long level is caught by a
  published test that needs no training.
- An unlocked phone in someone else's hands gives everything away: saved
  passwords open the messages, and spyware sees what you see. A password
  that leaks opens every earlier message sent under it.
- Without a password (open mode) anyone can read the message, with Stecho or
  without it. That is for jokes and love notes, not for privacy.

**По-русски.**

- Голосовое или текстовое сообщение шифруется и прячется в обычной
  JPEG-фотографии, которая уходит через iMessage как обычное фото.
- С паролем сообщение без него не прочитать (AES-256-GCM; ключ получается из
  пароля через PBKDF2-SHA256, 600 000 итераций). Вся защита — в пароле, так
  что выбирай длинный.
- Stecho не скрывает, что в фото может быть сообщение. «Сообщения»
  показывают, каким приложением фото отправлено, а статистический тест может
  его заметить: чем длиннее сообщение, тем проще. Сообщение на уровне
  «Длинные» находит опубликованный тест, которому не нужно обучение.
- Разблокированный телефон в чужих руках ничего не скрывает: сохранённые
  пароли открывают сообщения, а шпионская программа видит то же, что и ты.
  Если пароль утёк, им откроются и все сообщения, отправленные с ним раньше.
- Без пароля (открытый режим) сообщение прочтёт кто угодно, со Stecho или
  без него. Такой режим — для шуток и любовных записок; для защиты переписки
  он не годится.

## 1. What Stecho does

Stecho hides a short voice note or a text in a JPEG photo and sends the
photo through iMessage as an ordinary image attachment. The recipient drags
the photo into Stecho, or copies and pastes it there, and hears or reads the
message.

Before anything is hidden, the photo is encoded the way Apple encodes a
photo for sharing: scaled to the carrier size (2048 or 3024 px on the long
side), cropped to whole 16 px blocks and written by Apple's own JPEG encoder
at quality 0.85 in Apple's sharing colour profile, with a minimal EXIF
block. The message bits go into the non-zero AC coefficients of all three
colour planes; content-adaptive costs and syndrome-trellis codes put the
changes where the photo hides them best (`juniward-layer.md` §V2).

**The rate follows the message.** The layer has five rates, from 0.025 to
0.4 bits per non-zero AC coefficient. The app takes the smallest one that
holds the message, up to the ceiling of the level you chose: Hidden (0.1),
Balanced (0.2, the default) or Long (0.4); the free tier gets one rate
lower. The rate is not written anywhere: the decoder tries all five. At
Balanced, a typical iPhone photo holds about 18 s of voice at 2048 px and
about 34 s at 3024 px (simulated on five photos, `juniward-layer.md` §V2.10;
an estimate, not a promise).

Two modes share the layer:

- **Open mode** (`open-v2.md`): free, no password. The stream starts with
  the `SECO` marker, a version, a type and a length.
- **Stealth mode** (`stealth-v2.md`): Pro, a password both people know. The
  message is encrypted, and laid out in an order of the photo's coefficients
  that depends on the password. No marker, no length in clear.

## 2. What it protects

### 2.1 The content

The message is encrypted with AES-256-GCM before it is hidden. The key comes
from your password through PBKDF2-HMAC-SHA256 with 600 000 iterations and a
random 16-byte salt for each message (`stealth-v2.md` §5). Without the
password the hidden bytes look random.

**The password is the whole defence.** The format and the app are public, so
whoever holds a photo can try passwords as fast as PBKDF2 runs, and graphics
cards run it quickly. The order the coefficients are read in also comes from
the password, but with a fixed salt (`stealth-v2.md` §2.1), so that part can
be prepared once for every Stecho user; each guess then costs one PBKDF2 run
per photo and rate (§10 there). A short or reused password turns a saved
photo into a readable one; the app colours the password field by strength
and refuses nothing. For scale: six lowercase letters are about 3 × 10^8
possibilities (28 bits), four random words from a list of 7 776 about 4 ×
10^15 (52 bits). How many guesses a second an attacker manages depends on
their hardware; we have not measured it†. "Pair in person" avoids the
problem: one phone makes a random 128-bit password and hands it to the other
through two QR codes, so nobody invents or types one.

Why PBKDF2 and not Argon2id, which would cost an attacker more per guess:
PBKDF2 is the only password function in Apple's SDK†, and Argon2id would put
third-party cryptography into the app and into every reference decoder.

### 2.2 Integrity, and one answer for every failure

The GCM tag covers the encrypted message, the salt and the nonce. Change one
hidden bit and the check fails. A wrong password, a message that was changed
on the way and a photo with no message all get the same answer, on purpose:
the screen does not show whether a particular photo holds something you
cannot open.

### 2.3 No app marker in the stream

A stealth message has no magic bytes, no version and no length in clear. It
starts with the random salt, and trying a password costs the same whether
the photo is Stecho's or not (`stealth-v2.md` §4, §7). A scanner that looks
for a known signature has nothing to match. This is protection against
signature scanners, not against statistics (§3.1).

### 2.4 Open mode

Open mode needs no password. Anyone with Stecho, or with the specification
and its reference decoder, reads the message. The stream starts with the
`SECO` marker, which names the app on purpose. An open message also points
at the encrypted ones next to it: same chat, same app. It is for jokes and
love notes, never for anything that matters, and the composer says so every
time it is about to send one.

## 3. What it does not protect

### 3.1 That a photo carries a message

A statistical test can tell a photo with a message from one without, without
reading the message. How well depends on how much is hidden, on the photo
and on the test.

**What the app writes.** The cover is Apple's own JPEG encode of the
picture, so a photo with no message is byte-identical to what Apple would
write (59 of 59 photos, 2026-11-09). Stecho's encoder adds no mark of its
own. What a detector can look for is the embedding, and that grows with the
rate.

**What we measured.** Photos with a message, made by the app's engine in the
simulator, against Apple's encode of the same picture. The score is AUC: 0.5
is a coin flip, 1.0 is caught every time. Records:
`experiment-steganalysis-v2-si.md` for the first two sets,
`experiment-steganalysis-v2-app.md` for the third.

| Level | Detector | 8 photos, iPhone 15 Pro, 2026-11-07/08 | 59 photos, iPhone 15 Pro and 12 mini, 2026-11-09 | 120 photos, ten iPhone 14 Pro, 2026-11-20 |
|---|---|---|---|---|
| Hidden, and short messages at any level | trained | 0.49–0.54 | 0.52 | 0.53–0.54 |
| | untrained | 0.52–0.67 | 0.55–0.57 | 0.51–0.54 |
| Balanced (the default) | trained | 0.52–0.54 | 0.55 | 0.57 |
| | untrained | 0.50–0.69 | 0.53 | 0.66 at 3024 px, 0.75 at 2048 px |
| Long | trained | 0.59–0.71 | 0.68 | 0.76–0.77 |
| | untrained | 0.98–1.00 | 0.98 | 0.97–1.00 |

The untrained test is the F5 calibration attack of 2002, a few dozen lines
of code. The trained one is a DCTR feature set with a linear classifier:
trained on 72 sources for the first set, cross-validated on the set itself
for the other two. The first set is whole photos and crops at 2048 and 3024
px; the second is whole photos at 3024 px; the third, from a public research
collection, at both sizes.

- **A Long message is caught** by a published test with no training, on
  every set. The app says so when a message passes the Balanced line.
- **Balanced depends on the photos.** The untrained test scored 0.53 on our
  own 59 photos and 0.66 to 0.75 on the 120 from iPhone 14 Pro phones. Why
  they differ was not measured†, and we do not say which is typical.
- **Hidden stayed near a coin flip on the two larger sets** (0.57 at most)
  and reached 0.67 on the smallest. Read that as "hard to flag on these
  photos", not as "safe".
- **Smooth pictures are much easier to flag.** At Balanced the untrained
  test scored 0.84 on synthetic images and 0.98 on wallpaper crops (12 of
  each, 2026-11-07/08).
- **Photos that were already JPEGs at the carrier size** (24 of them,
  2026-11-07/08): the trained detector scored 0.51–0.53 up to Balanced and
  0.62 at Long. The untrained test does not work on them at all, with or
  without a message, so they are less well covered.
- **Stronger detectors exist.** No network has been trained on Stecho
  photos†. Four published, pretrained networks did no better than the
  detectors above on simulated photos (2026-11-04,
  `experiment-steganalysis-cnn.md`), which says little about one trained for
  the purpose.
- **With the original photo, nothing is hidden.** Apple's encode of the same
  pixels can be rebuilt (it matched on every photo we measured), and then
  every changed coefficient shows. The original stays in your Photos library
  unless you delete it. If the message matters, do not keep it.

Open and stealth photos at the same rate use the same layer, so they should
be equally detectable† (`open-v2.md` §8). A positive test shows that
something is hidden, never what.

### 3.2 The size of the message

A message fills one of the five rates, so a reader of the stream learns its
size to within a factor of two. In open mode that is anyone; in stealth
mode, only someone with the password. Without the password the rate can only
be estimated from how many coefficients changed; we have not measured how
well† (`stealth-v2.md` §10). A text and a minute of voice in the same photo
do change different numbers of coefficients.

### 3.3 The file and the "From Stecho" label

With no steganalysis at all, the file shows that an app made it:

- Its quantisation tables are those of quality 0.85. A photo that Messages
  re-encoded has quality-0.75 tables, so someone comparing the tables of
  received photos can tell the two apart† (tables measured 2026-11-03,
  `experiment-steganalysis.md`).
- Its EXIF block is minimal: colour space and pixel size, no camera and no
  location. Nothing from your original photo's metadata travels.
- Its sides are multiples of 16 px: a 4:3 photo at 3024 px leaves as 3024 ×
  2256, not 3024 × 2268.

None of this says what is inside, or that anything is. File size says
little: in a simulation the embedding changed it by at most 0.3 %, and a
score built on size alone reached 0.567 (2026-11-03; not repeated on the
current encoder†). Two photos made from one picture with different messages
still differ in size: the file is not padded.

Messages names the app that inserted an attachment: its long-press menu
carries a "From Stecho" item (n = 1 on the receiving phone, 2026-11-01,
`experiment-device-transport.md`), and a "From Stecho" line under a received
attachment was seen once (iPhone 12 mini, 2026-11-08). So the chat itself
can show which app sent the photo, even when the message inside did not
survive. "Copy instead of send" (Pro) lets you paste the photo yourself
instead; whether a pasted photo shows no such item has not been checked†.

### 3.4 Transport

Stecho needs the JPEG to arrive with its coefficients untouched.

| Case | Result | n | Date |
|---|---|---|---|
| A photo in Display P3 | Messages re-encodes it at about quality 0.75; the message is gone | 39 sends, with the next row | 2026-11-02 |
| A photo in Apple's sharing profile, in sRGB or with no profile | arrives byte for byte | same | 2026-11-02 |
| Stecho's carrier, both directions, text and voice | arrives byte for byte and decodes | 8 of 8 | 2026-11-02 |
| A carrier with the current cover, open mode | the sender's copy and the copy synced to a Mac are identical | 1 | 2026-11-09 |

Two phones, an iPhone 12 mini (iOS 26.7.2) and an iPhone 15 Pro (iOS 27.2),
one pair of Apple Accounts, Wi-Fi (`experiment-device-transport.md`,
`experiment-steganalysis-v2-si.md`). This is why the carrier is written in
the sharing profile; which property of the profile Messages looks at was not
separated. If Apple changes the pipeline, the message is destroyed and the
app says there is none.

Anything that re-encodes the photo destroys the message: a screenshot, an
edit, saving and sending it from another app. If the recipient is not on
iMessage, the photo may go out as MMS, which re-encodes images†. Stecho
works iMessage to iMessage only, and does not warn when a conversation is
not iMessage.

### 3.5 Your phone

- **Saved passwords.** Each chat has its own password, and keeping it is
  your choice each time ("Save for this chat"). Saved ones sit, with the
  date each was saved and any name you gave it, in a Keychain item that
  never leaves this phone: no iCloud Keychain, no move to a new phone with a
  backup. It sits in a Keychain group that only Stecho and its extension
  share, so other apps cannot read it; forensic tools on a phone unlocked
  since it was switched on can†. Switching encryption off does not remove
  saved passwords; Forget in Settings → Saved Passwords does. Deleting the
  app leaves the item in place† until Stecho is installed afresh, which
  wipes it.
- **The Face ID lock** is off by default. Off, whoever holds the unlocked
  phone opens every chat that has a saved password by dragging a photo into
  Stecho. On, the app asks for Face ID or the phone's passcode first: that
  stops a person who does not know the passcode, and nobody else. The lock
  is the app's own check: the Keychain item is not tied to Face ID, and the
  phone hands it to the app whenever it is unlocked. In the latest
  TestFlight build (2026-11-10) the lock also has gaps when it is on: a link
  into the app opens Saved Passwords and the guide without asking, the About
  tab opens the guide the same way, and the guide's switch turns the lock
  off, again without asking. The next build closes them.
- **Leaving the app.** In the latest TestFlight build (2026-11-10) nothing
  covers the screen when you leave: the app switcher keeps a picture of it,
  a revealed message is still there when you come back, and it can still be
  open when you use the extension in another chat. The next build covers the
  reading screen and, with the Face ID lock on, clears the message and locks
  again (checked in a simulator, 2026-11-15/16; not on a phone†). The
  composing screen is not covered in either.
- **Keyboard.** A third-party keyboard with Full Access can send what you
  type to its developer. Password fields are marked secure, which should
  bring up the system keyboard†; the message field is an ordinary one.
- **Drafts.** Stecho keeps no draft of a text. A voice note you have
  recorded and not yet sent is a file in the app's own storage until you
  send or discard it.
- **Clipboard.** "Copy instead of send" puts the photo on the pasteboard for
  you to paste. That copy stays on this phone (Universal Clipboard does not
  relay it) and expires after two minutes; until then other apps on the
  phone can read it. In the latest TestFlight build (2026-11-10) it does not
  expire yet. "Paste instead of drag" uses Messages' own Copy, which Stecho
  does not control: that copy can reach your other devices through Universal
  Clipboard† and stays until something replaces it. Dragging never touches
  the pasteboard.
- **Spyware and other eyes.** Anything that reads the screen or the keyboard
  sees the message in clear. So does a person looking over your shoulder, a
  screenshot the recipient takes, or VoiceOver reading the text aloud. A
  jailbroken phone protects nothing.
- **Coercion.** Someone who can make you unlock the phone or say the
  password gets the messages. There is no decoy password and no hidden
  second mode.

### 3.6 The recipient's phone and backups

Everything in §3.5 is true of the other phone too, and a careless or
unfriendly recipient is beyond what an app can fix. The photo stays in both
Messages histories and in their backups; in iCloud that means Apple's
storage, under keys Apple holds unless Advanced Data Protection is on†.
Saved passwords do not travel with a backup to another phone, but a photo
from a backup plus a password learned some other way is a readable message.

### 3.7 Who talks to whom

Stecho changes nothing about the conversation around the photo: who wrote to
whom and when is as visible as for any iMessage, and so is the fact that two
people keep exchanging photos.

### 3.8 Past messages

There is no forward secrecy: a password that leaks opens every message ever
sent under it. Changing that would take a key exchange for every message,
which a photo cannot carry. Each chat has its own password, so a leak costs
one chat. If you suspect one, set a new password; it protects what comes
next and nothing sent before.

### 3.9 Network requests the app makes

Stecho has no server and no accounts, and its code calls no analytics or
tracking service: it imports Apple's frameworks and the Opus audio codec,
nothing else (read 2026-11-20). Purchases go through Apple's App Store. It
does show maps, and maps come from Apple.

**A map preview reaches Apple Maps without a tap.** When a revealed text
holds coordinates (an attached location, `geo:`, or a map link with
coordinates in it), the reading screen draws a map preview at once: Apple's
map servers receive the area around the coordinates, from the recipient's
IP, at the moment of reading. On the sending side the location picker loads
map tiles, and place search sends what is typed to Apple. Stecho itself
sends the coordinates nowhere. For a message that *is* a place, the area
Apple sees is most of what it says; to keep a place away from Apple, send it
as plain text, not as an attached location or a map link.

**A tap on the preview opens a Safari sheet** inside Messages:

| The revealed text holds | The tap opens | That host sees |
|---|---|---|
| `geo:` (an attached location) | `maps.apple.com` at those coordinates | the recipient's IP and the place |
| an Apple Maps link | the link as sent | the same |
| a Google Maps (`google.com/maps`, `goo.gl/maps`, `maps.app.goo.gl`), Yandex Maps (`yandex.ru/com/ua/kz/by` `/maps`) or Waze (`waze.com`) link | the link as sent | the recipient's IP, the full link (with anything the sender put in it, such as a parameter that ties the open to this message), and that it was opened now |

A map link with no coordinates in it draws no preview, so there is nothing
to tap. Nothing loads from a third-party host without the tap, and a link to
any other host gets no preview. In the latest TestFlight build (2026-11-10)
the links, phone numbers and addresses in a revealed text are still
detected, and a long press on a detected link may load a preview from the
sender's address†; the next build shows plain text.

## 4. At a glance

### 4.1 Guarantees per mode

|  | Open mode | Stealth mode |
|---|---|---|
| Keeps the message unreadable | ❌ | ✅ AES-256-GCM, as strong as the password (§2.1) |
| Notices any change to the message | ❌ | ✅ GCM tag (§2.2) |
| No app marker in the hidden stream | ❌ `SECO` | ✅ (§2.3) |
| Hides the size of the message | ❌ stated in the stream | ⚠ to a factor of two for a password holder; an estimate for others (§3.2) |
| Hides that the photo carries a message | ❌ (§3.1) | ❌ (§3.1) |
| Hides which app sent it | ❌ (§3.3) | ❌ (§3.3) |
| Survives iMessage between two iPhones | ✅ measured (§3.4) | ✅ same |
| Survives re-encoding, screenshots, MMS | ❌ (§3.4) | ❌ (§3.4) |
| Protects earlier messages if the password leaks | — | ❌ (§3.8) |
| Holds on an unlocked or compromised phone | ❌ (§3.5) | ❌ (§3.5) |

### 4.2 Who sees what

| Who | What they see | What stays protected |
|---|---|---|
| **Someone who picks up your unlocked phone** | Stecho among the apps; a normal-looking photo; "From Stecho" on a long press (§3.3); every chat with a saved password, if the Face ID lock is off (§3.5) | Stealth messages whose password is not saved |
| **Someone with a copy of the photo** (a backup, a forward, the other phone) | Open messages in full. With a published test: a clear flag at Long and on smooth pictures; at Balanced, from nothing to a moderate flag, depending on the photos; little at Hidden (§3.1). The file's tables, EXIF and sides (§3.3) | Stealth content, as long as the password holds (§2.1) |
| **Someone with extraction tools and the unlocked phone** | The saved passwords†, so every chat that has one, earlier messages included (§3.5, §3.8); the Messages history | Chats whose password was never saved, as long as it is strong |
| **Spyware on the phone** | What you see, hear and type | Nothing (§3.5) |

Stecho keeps what a message says between two iPhones whose owners trust each
other. It is not built to withstand an examination of either phone, or
someone who screens photos statistically.

### 4.3 When a message goes out in stealth mode

Three things have to hold: Pro, encryption switched on, and a password for
this chat. Otherwise the message goes out open, and the composer says so
before you send. The app never changes one of the three to make up for
another.

- **One password per chat.** A chat is recognised by identifiers that
  Messages gives the extension. They changed when the app was installed
  again over itself, and survived a TestFlight update (measured for Stiger:
  developer installs on iOS 27.2 and 26.7.2, the update on iOS 27.2,
  2026-11-02/03; not repeated for Stecho†). So the link between a saved
  password and its chat can break, and the app does not rely on it alone.
- **Reading tries saved passwords.** Stecho makes one automatic try, with
  the chat's own password. The other saved passwords wait in a "Saved
  passwords" menu, one try per pick, because a wrong try here costs a whole
  decode: up to five rates and six PBKDF2 runs (`stealth-v2.md` §9). So a
  message under any password saved on your phone can be opened in any chat.
- **In the latest TestFlight build (2026-11-10), reading can move a chat to
  another password.** When a saved password other than the chat's own opens
  a message, by the automatic try or by a pick from the menu, it becomes the
  chat's password without asking: whoever knows any password saved on your
  phone can get a chat moved onto it. From the next build a read moves
  nothing: the reading screen says that another saved password opened the
  message and, in a chat with no password, offers a switch, off by default,
  to keep it.

## 5. Assumptions and what is unverified

Stecho's claims hold if your password is long and used nowhere else; the
other person got it in person ("Pair in person") or over a channel you
trust; neither phone is jailbroken or runs spyware; Apple's cryptography
(CryptoKit, CommonCrypto, `SecRandomCopyBytes`) is correct and the
primitives hold; and iMessage keeps delivering the photo unchanged (§3.4),
which is observed behaviour, not Apple's promise.

**† Not checked by us.** Recalled, assumed, inferred, or measured for a
sibling only:

- that iOS keeps Keychain items after an app is deleted, and that extraction
  tools reach them (§3.5): recalled;
- that iOS shows its own keyboard for a secure field (§3.5): set in the
  code, not tested;
- that Apple's SDK has no password function besides PBKDF2 (§2.1): checked
  once, against the iOS 27.2 SDK on 2026-11-10, and no record was kept; how
  fast an attacker guesses: not measured;
- how iCloud protects Messages and backups (§3.6): recalled, not read at the
  source;
- that a local-only pasteboard item stays off Universal Clipboard, and that
  a copy made in Messages travels through it (§3.5): the first is a flag set
  in the code, neither was measured;
- what the app switcher shows on a real phone (§3.5): simulator only;
- whether a pasted photo shows no "From Stecho" item (§3.3);
- the chat identifiers after a reinstall or an update (§4.3): measured for
  Stiger, which shares the code, and for a TestFlight update only;
- a detector trained on Stecho photos and a test written for layer v2
  (§3.1); why Balanced scores differently on the 59 and the 120 photos; that
  open and stealth photos are equally detectable: inferred from the format;
- how well the message size can be estimated without the password (§3.2),
  and the file-size figure on the current encoder (§3.3);
- that a reviewer can use the quantisation tables (§3.3): inferred from the
  tables, not tried;
- MMS (§3.4): recalled; transport on other iOS versions, on cellular, from
  an iPad or a Mac, and with Messages' low-quality image mode on: not
  measured;
- what a long press on a detected link loads inside Messages (§3.9): not
  measured;
- the 2048 px size made from a camera original on a phone, where the image
  library rounds differently (§3.1).

## 6. How to verify and where to report

Everything needed to check Stecho's claims about the format is in
<https://github.com/axlerk/stecho-protocol>:

| File | What it holds |
|---|---|
| `juniward-layer.md` | From JPEG coefficients to a byte stream: which coefficients, the rates, the codes |
| `open-v2.md`, `stealth-v2.md` | The two modes: framing, key derivation, AES-256-GCM, the order a decoder tries things in |
| `reference/python/` | A reference encoder and decoder that share no code with the app |
| `test-vectors/` | Photos, passwords and the expected messages |

The app's engine reads the vectors the Python encoder wrote, and the Python
decoder reads vectors the app wrote. A decoder written from the
specification alone can open a photo from your own chat without Stecho.

Found a gap between this document and the app, or between the app and the
specification? Open an issue at
<https://github.com/axlerk/stecho-protocol/issues>. For an attack on the
format, write first to hello@onegoodman.studio with `[SECURITY]` in the
subject.

## 7. History

| When | What changed | What it means for old photos |
|---|---|---|
| 2026-11-10 | The app stopped reading layer v1 | A photo made by the first TestFlight build (2026-11-05) reads as a photo with nothing in it |
| 2026-11-08 | The cover became Apple's own JPEG encode | Photos made by the TestFlight builds of 2026-11-05 to 2026-11-08, after the first one, carry the mark of Stecho's own encoder: detectors told them from Apple's files at AUC 0.76–0.90, with or without a message (8 and 59 photos, 2026-11-07 to 09) |
| 2026-11-04 | Layer v2 replaced v1 | v1 used one fixed, high rate; a 2002 test with no training told its photos from ordinary ones at AUC 0.98–1.00 (150 synthetic and wallpaper sources and 5 iPhone photos, 2026-11-02/03) |

The measurements of the earlier layers are in `experiment-steganalysis.md`
and `experiment-steganalysis-v2-si.md`.

## Glossary

| Term | Meaning |
|---|---|
| AES-256-GCM | The cipher: encrypts the message and detects any change to it |
| AUC | A detector's score: 0.5 is a coin flip, 1.0 is caught every time |
| Carrier | The photo a message is hidden in |
| Cover | The same photo before anything is hidden in it |
| Forward secrecy | A leaked key does not open earlier messages. Stecho does not have it (§3.8) |
| Open mode / stealth mode | Without a password, readable by anyone, with Stecho or without it / with a password, encrypted |
| PBKDF2 | Turns a password into a key, slowly on purpose (RFC 8018) |
| Rate | How much is hidden: bits per non-zero AC coefficient, one of five steps |
| Steganalysis | Detecting that something is hidden, without reading it |
| Trained / untrained detector | A classifier that learned from examples (here DCTR features) / a fixed published test (here the F5 calibration attack) |
