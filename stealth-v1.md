# Stealth Mode v1 (`stealth-v1`)

The mode used by **Pro-tier** Stecho. The carrier is a Stecho JPEG whose
embedded payload is wrapped in AES-256-GCM under a password-derived key,
and laid out in DCT-coefficient LSBs in a password-derived permuted
order. Without the password, an attacker cannot reconstruct the
permutation, cannot read coherent bytes from the stream, and cannot
verify the AES-GCM tag — three independent walls between them and the
plaintext.

This document defines the wire format. The shared embedding layer
(J-UNIWARD distortion + STC) is described in
[`juniward-layer.md`](juniward-layer.md); this document only specifies
how stealth mode parameterises that layer.

For threat-model claims and the adversaries this is designed to resist,
see [`THREAT_MODEL.md`](THREAT_MODEL.md).

> **Notation.** All multi-byte integer fields are little-endian unless
> stated otherwise. `||` is byte-string concatenation.

## 1. Inputs

- `jpeg` — baseline or progressive JPEG carrier.
- `password` — UTF-8 bytes of the user's passphrase. Non-empty.
- `type_tag` — `0x01` (text) or `0x02` (audio-opus); other values rejected.
- `body` — the payload bytes.

## 2. Permutation

Stealth mode uses a permutation derived from the password alone:

### 2.1 Permutation key

```
perm_key = PBKDF2-HMAC-SHA256(
              password = password_utf8,
              salt     = ASCII("stecho-stealth-v1-perm-salt"),    # 27 bytes
              iter     = 600000,
              dkLen    = 32)
```

The PBKDF2 salt is a fixed protocol constant, **not** a per-message
random value. This lets the decoder reconstruct the permutation
before reading any JPEG bytes. The per-message AES key (§4) uses a
separate random per-message salt.

### 2.2 Keystream

```
keystream(L) = HMAC-SHA256(perm_key, BE32(0)  || INFO)
            || HMAC-SHA256(perm_key, BE32(1)  || INFO)
            || ...
            truncated to L bytes

INFO    = ASCII("stecho-stealth-v1-perm")     # 22 bytes
BE32(c) = c encoded as 4-byte big-endian
```

### 2.3 Fisher–Yates shuffle

```
ks = keystream(N * 4)
indices = [0, 1, ..., N - 1]
for i = N - 1 down to 1:
    r = uint32_be(ks[i*4 .. i*4 + 4])
    j = r mod (i + 1)
    swap indices[i] and indices[j]

π = indices
```

Logical step `s` of the permuted walk visits
`positions[π[s]]`.

## 3. Embedding rate

Stealth mode uses **`α = 0.08` bits per non-zero AC coefficient**, fixed
at the v1 protocol level, identical to open mode (`open-v1.md` §3).
This means a stealth-mode JPEG and an open-mode JPEG have the same
statistical embedding profile — they differ only in what's in the
permuted bit stream, not in how much of it there is.

The encoder MUST NOT vary `α`. The decoder MUST assume `α = 0.08`.

## 4. Plaintext stream layout

The byte stream extracted via STC at the password-derived permutation
has this layout:

```
offset    size                              field
------    ----                              ----------------------------
 0         16                               aes_salt        per-message random
16         12                               aes_nonce       per-message random
28         remainder of stream              ciphertext_with_tag
```

There is **no plaintext magic, no version, no length** outside the
AES-protected region. The entire stream after `aes_salt || aes_nonce`
is ciphertext + GCM tag, filling the rest of the available capacity.
Decoder authentication via GCM tag is the only positive signal that a
JPEG contains a stealth-mode payload at all.

```
stream_size_bytes = floor(0.08 × N / 8)
ciphertext_with_tag_size = stream_size_bytes - 28
plaintext_size = ciphertext_with_tag_size - 16   # subtract GCM tag
```

> **Why no plaintext length field.** Stiger's stealth-v3 made the same
> choice and the reasoning carries over: any plaintext field gives an
> attacker a cheap oracle that a wrong-password attempt can short-
> circuit *before* paying the per-attempt cost of PBKDF2 + STC decode.
> By leaving everything inside GCM, the only oracle is "GCM tag
> verifies" — which costs the full PBKDF2 + STC + GCM operation per
> candidate.

## 5. AES-256-GCM

### 5.1 Key derivation

```
aes_key = PBKDF2-HMAC-SHA256(
              password = password_utf8,
              salt     = aes_salt,      # 16 bytes from §4 (per-message)
              iter     = 600000,
              dkLen    = 32)
```

Two PBKDF2 derivations therefore happen per encode/decode operation:
one for `perm_key` (fixed-salt) and one for `aes_key` (per-message
random salt). They produce different keys from the same password —
a salt collision is impossible.

### 5.2 AAD

```
AAD = aes_salt(16) || aes_nonce(12) = 28 bytes
```

The entire plaintext-stream header is authenticated. Tampering with any
of these bytes fails GCM verification.

### 5.3 Inner plaintext

The plaintext that AES-GCM seals is:

```
offset    size                  field
------    ----                  -------------------------------------
 0         1                    type_tag    0x01=text, 0x02=audio-opus
 1         4                    body_len    LE uint32
 5      body_len                body        payload bytes
5+body_len     rest             padding     random fill to plaintext_size
```

Padding fills the inner plaintext to `plaintext_size` (§4) so the
ciphertext exactly fills the embedded capacity. Decoder MUST ignore
padding after `body_len` bytes of body.

`body_len` MUST satisfy `0 ≤ body_len ≤ plaintext_size - 5`. A value
outside the range is treated as authentication failure (return None).

### 5.4 Seal / open

```
ciphertext_with_tag = AES-256-GCM.seal(
    key       = aes_key,
    nonce     = aes_nonce,
    aad       = AAD,
    plaintext = inner_plaintext
)
# ciphertext_with_tag = ciphertext || tag(16)
# its length equals plaintext_size + 16 = ciphertext_with_tag_size
```

Decoder:
```
inner_plaintext = AES-256-GCM.open(
    key            = aes_key,
    nonce          = aes_nonce,
    aad            = AAD,
    ciphertext_tag = ciphertext_with_tag
)
```

Any GCM failure (tag mismatch, malformed input) MUST be treated as
"no Stecho payload" (§7). Decoder MUST NOT distinguish "wrong password"
from "not a Stecho JPEG" in user-facing errors.

## 6. Capacity

```
stealth_payload_max_bytes = floor(0.08 × N / 8) - 28 - 16 - 5
                          = floor(0.08 × N / 8) - 49
```

Subtracting the 28-byte salt+nonce header, the 16-byte GCM tag, and the
5-byte inner header (type + body_len).

For typical iPhone carriers (same `N` as `open-v1.md` §5):

| Carrier               | stealth capacity | Voice (12 kbps Opus) |
|-----------------------|------------------|----------------------|
| 1024×1024             | 10 KB            | ~6 s                 |
| 2048×2048             | 40 KB            | ~25 s                |
| 4032×3024 (12 MP)     | 140 KB           | ~87 s                |
| 4032×3024 (24 MP)     | 280 KB           | ~175 s               |

> For longer voice content the user must select a higher-resolution
> carrier. The compose UI surfaces this as the camera "traffic light"
> (favours large, textured shots) and the Photos picker capacity
> countdown (shows max recording length for the picked photo).

## 7. Decoder algorithm (normative)

```
fn decode_stealth(jpeg, password) -> Option<(type_tag, body)>:
    spectral = parse_jpeg(jpeg)
    if spectral == None: return None
    N = position_count(spectral)
    stream_size_bits = floor(0.08 × N)
    stream_size_bytes = stream_size_bits // 8
    if stream_size_bytes < 28 + 16 + 5: return None      # carrier too small

    # Derive permutation key (slow — PBKDF2-600k).
    pi = stealth_permutation(password, N)

    # STC-decode the entire stealth-mode stream.
    bits = juniward_layer.decode(
        jpeg    = jpeg,
        pi      = pi,
        message_length = stream_size_bits,
        alpha   = 0.08,
    )
    stream = bits_to_bytes(bits, stream_size_bytes)

    # Parse plaintext header.
    aes_salt  = stream[0..16]
    aes_nonce = stream[16..28]
    ct_tag    = stream[28..stream_size_bytes]

    # Derive AES key (slow — PBKDF2-600k).
    aes_key = pbkdf2(password, aes_salt, 600000, 32)
    aad     = aes_salt || aes_nonce
    try:
        inner = aesgcm_open(aes_key, aes_nonce, aad, ct_tag)
    except AuthFailure:
        return None

    # Parse inner plaintext.
    if len(inner) < 5: return None
    type_tag = inner[0]
    if type_tag not in {0x01, 0x02}: return None
    body_len = u32_le(inner[1..5])
    if body_len > len(inner) - 5: return None
    body = inner[5..5+body_len]
    return Some((type_tag, body))
```

The decoder pays roughly `2 × PBKDF2-600k + 1 × STC-decode + 1 × GCM-open`
per stealth attempt. On Apple Silicon this is sub-second total; on
A9-class iPhones (iOS 15 floor) approximately 1-2 seconds. Per
Stecho's UX rules, the compose surface shows a "decrypting…" indicator
while a stealth attempt is in flight.

## 8. Composition with open-v1 (informative)

The top-level decoder (running in the iMessage extension or container
app) MUST first attempt `open-v1` decode (free, no password input, no
PBKDF2 cost) and only fall through to `stealth-v1` if the user has
provided a password. Specifically:

```
fn decode_any(jpeg, password_opt):
    if open_v1.decode(jpeg) is Some(result):
        return ("open", result)
    if password_opt is None:
        return None       # cannot try stealth without password
    if stealth_v1.decode(jpeg, password_opt) is Some(result):
        return ("stealth", result)
    return None
```

Some downsides of this dispatch order:

- Adversary can verify a JPEG is **not** open-mode (cheap STC decode +
  missing `SECO` magic) without trying stealth. Open mode is publicly
  identifiable by design.
- The order biases the decoder to try open first; if both modes happen
  to validate (vanishingly unlikely — `SECO` magic plus consistent
  length), open wins. Mode authors should pick distinct magic /
  cryptographic markers to avoid collisions even in unlikely cases.
  Stealth has no magic, so the only way both validate is if a
  stealth-encoded message happens to have the bytes `SECO || 0x01 || ...`
  at the right offset *and* its STC stream decodes consistently against
  the identity permutation, which has probability `~2^-80`.

## 9. Threat model summary

A full threat model lives in [`THREAT_MODEL.md`](THREAT_MODEL.md).
This section restates only what `stealth-v1` adds on top of the layer's
properties (see [`juniward-layer.md`](juniward-layer.md) §8).

**Defended:**

- **Content confidentiality** under AES-256-GCM with a PBKDF2-derived
  key. Brute-force cost: `~PBKDF2-600k` per password candidate, times
  the number of candidates.
- **Content authenticity.** GCM tag verification ensures that any
  tampering with the JPEG (DCT coefficient flips, header bytes,
  permutation positions) fails authentication rather than silently
  yielding modified plaintext.
- **No fixed-byte fingerprint.** The first bytes of the stealth stream
  are `aes_salt`, which is uniformly random per message. There is no
  magic constant in the wire byte order that lets a passive observer
  fingerprint stealth Stecho JPEGs.
- **Indistinguishability of wrong-password from non-Stecho.** Both
  return `None`. The decoder cannot give an attacker an oracle for
  "this JPEG carries a Stecho message" without knowing the password.

**Not defended:**

- **Statistical detectability of J-UNIWARD modification.** See layer
  spec §8 — at `α = 0.08` modern CNN-class detectors detect with
  ~70-78% accuracy on standard test corpora. Stealth mode does not
  hide *the fact* of an embedding; it hides *the content*.
- **iMessage transport recompression.** Spec assumes the carrier
  reaches the recipient with DCT coefficients preserved byte-for-byte.
  See [`THREAT_MODEL.md`](THREAT_MODEL.md) §4.3 for the failure
  mode and §6.3 for the MMS downgrade case.
- **Forward secrecy.** A password leak retroactively decrypts every
  prior stealth-mode message under that password.

## 10. Stability

`stealth-v1` is frozen on first ship. Incompatible changes require a
new version (`stealth-v2.md`) and a new permutation info-tag
(e.g. `stecho-stealth-v2-perm`). The two protocol constants
(`stecho-stealth-v1-perm-salt`, `stecho-stealth-v1-perm`) are
permanent identifiers for this version.

## 11. Glossary

| Term            | Definition                                                       |
|-----------------|------------------------------------------------------------------|
| `aes_salt`      | The 16-byte AES-key-derivation salt at stream offset 0           |
| `aes_nonce`     | The 12-byte AES-GCM nonce at stream offset 16                    |
| `perm_key`      | The 32-byte PBKDF2-derived key used to seed the permutation `π`  |
| permutation `π` | Password-keyed bijection of `[0, N)` over the canonical AC list |
| `INFO`          | The fixed ASCII tag used in the permutation keystream            |
