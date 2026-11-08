# Stealth Mode v2 (`stealth-v2`)

The mode used by **Pro-tier** Stecho on embedding layer v2. The payload is
wrapped in AES-256-GCM under a password-derived key and laid out in a
password-derived order of the cover. Without the password an attacker
cannot reconstruct the order, read coherent bytes, or verify the GCM tag.

This document defines how stealth mode frames its message on top of
[`juniward-layer.md`](juniward-layer.md) layer v2 (§V2.1–§V2.13). It
replaces [`stealth-v1.md`](stealth-v1.md) for new carriers; v1 carriers
stay readable (§8).

Status: draft. The layer's open items apply; two are specific to this
mode: the PBKDF2 run per rung tried (O3, §9) and the reuse of v1's
permutation salt (O8, §2.1) ([`juniward-layer.md`](juniward-layer.md),
"Open").

For threat-model claims see [`THREAT_MODEL.md`](THREAT_MODEL.md)
(not yet updated for v2).

> **Notation.** All multi-byte integer fields are little-endian unless
> stated otherwise. `||` is byte-string concatenation.

## 1. Inputs

- `jpeg` — baseline or progressive JPEG carrier (or pixels, for an encoder
  that quantises them itself).
- `password` — UTF-8 bytes of the passphrase. Non-empty.
- `type_tag` — `0x01` (text, UTF-8) or `0x02` (audio-opus); other values
  rejected. The audio body is the app's Opus container (layer O5).
- `body` — the payload bytes.

## 2. Permutation

### 2.1 Permutation key

```
perm_key = PBKDF2-HMAC-SHA256(
              password = password_utf8,
              salt     = ASCII("stecho-stealth-v1-perm-salt"),    # 27 bytes
              iter     = 600000,
              dkLen    = 32)
```

This is **the same key as stealth-v1** (§2.1 there). The versions are
separated by the keystream info tag (§2.2) and by the cover itself (v1
permutes all `N` AC slots, v2 the `n` non-zero ones). Reusing the key means
one PBKDF2 run gives the permutation for both versions, so a decoder that
tries both pays for it once (O8: a choice of this draft, to be reviewed).

### 2.2 Order

The layer's keyed permutation (§V2.4) over the `n` cover elements with

```
key  = perm_key
info = ASCII("stecho-stealth-v2-perm")                  # 22 bytes
```

v1's info tag was `"stecho-stealth-v1-perm"`; with the same `perm_key` and
the same `n`, the two keystreams are unrelated.

## 3. Rate

The layer's rate ladder (§V2.5): rung `k` gives a stream of
`L_k = floor(n × q_k / (8 × d_k))` bytes. The encoder picks the rung; the
decoder tries rungs 1 to 5 in that order (§7). Stealth and open carriers at
the same rung embed the same number of bits with the same layer.

## 4. Stream layout

The `L_k`-byte stream of the chosen rung:

```
offset    size                              field
------    ----                              ----------------------------
 0         16                               aes_salt        per-message random
16         12                               aes_nonce       per-message random
28         L_k − 28                         ciphertext_with_tag
```

As in v1 there is **no plaintext magic, version or length**. The GCM tag
is the only signal that a stream holds a stealth payload.

```
ciphertext_with_tag_size = L_k − 28
plaintext_size           = L_k − 44          # minus the 16-byte GCM tag
```

What is new is only the stream size: `L_k` of the chosen rung instead of
v1's whole-carrier stream (proposal §3.6).

## 5. AES-256-GCM

Identical to stealth-v1 §5:

```
aes_key = PBKDF2-HMAC-SHA256(password_utf8, aes_salt, 600000, 32)
AAD     = aes_salt || aes_nonce                          # 28 bytes
```

Inner plaintext, `plaintext_size` bytes:

```
offset    size                  field
------    ----                  -------------------------------------
 0         1                    type_tag    0x01=text, 0x02=audio-opus
 1         4                    body_len    LE uint32
 5      body_len                body        payload bytes
5+body_len     rest             padding     random, to plaintext_size
```

`ciphertext_with_tag = AES-256-GCM.seal(aes_key, aes_nonce, AAD, inner)`,
`plaintext_size + 16` bytes. `body_len` MUST satisfy
`body_len ≤ plaintext_size − 5`; a value outside the range is treated as
authentication failure. Any GCM failure means "no payload at this rung".
Decoders MUST NOT distinguish "wrong password" from "not a Stecho JPEG" in
user-facing errors.

## 6. Capacity

```
stealth_capacity(k) = L_k − 28 − 16 − 5 = L_k − 49
```

A rung with `L_k < 49` is unusable. With the default Balanced preset Pro
may use rungs 1–4, free (if it ever sends stealth) rungs 1–3 (layer
§V2.5.3). The encoder MUST refuse a body larger than `stealth_capacity`
of its highest allowed rung. Example figures in voice seconds: layer
§V2.10.

## 7. Decoder (normative)

```
fn decode_stealth_v2(jpeg, password, perm_key = None) -> Option<(k, type_tag, body)>:
    if perm_key is None:
        perm_key = pbkdf2(password, "stecho-stealth-v1-perm-salt", 600000, 32)
    perm_for_n = n -> keyed_permutation(perm_key, "stecho-stealth-v2-perm", n)
    for (k, stream) in layer_v2_streams(jpeg, perm_for_n, min_bytes = 49):
        aes_salt  = stream[0..16]
        aes_nonce = stream[16..28]
        aes_key   = pbkdf2(password, aes_salt, 600000, 32)     # once per rung tried
        try:
            inner = aesgcm_open(aes_key, aes_nonce, aes_salt || aes_nonce, stream[28..])
        except AuthFailure:
            continue
        type_tag = inner[0]
        if type_tag not in {0x01, 0x02}: continue
        body_len = u32_le(inner[1..5])
        if body_len > len(inner) − 5: continue
        return Some((k, type_tag, inner[5 .. 5 + body_len]))
    return None
```

Rungs are tried in ascending order; the first that authenticates wins
([`juniward-layer.md`](juniward-layer.md) §V2.5.2).

## 8. Composition with open mode and with v1 (normative order)

A decoder that reads every version tries, in this order:

```
fn decode_any(jpeg, password_opt):
    if open_v2.decode(jpeg) is Some(r):   return ("open", "v2", r)
    if open_v1.decode(jpeg) is Some(r):   return ("open", "v1", r)
    if password_opt is None:              return None
    perm_key = pbkdf2(password, "stecho-stealth-v1-perm-salt", 600000, 32)
    if stealth_v2.decode(jpeg, password, perm_key) is Some(r): return ("stealth", "v2", r)
    if stealth_v1.decode(jpeg, password, perm_key) is Some(r): return ("stealth", "v1", r)
    return None
```

- Open before stealth, as in v1: open costs no PBKDF2.
- v2 before v1: new carriers are v2.
- A decoder MAY leave out the v1 steps (layer O7); it then cannot read v1
  carriers and changes nothing else.
- Collisions: a stealth stream that also parses as open would need
  `SECO || 0x02` (or `0x01`) and a consistent length at the right offset
  of a stream read in the wrong order, about 2⁻⁴⁰ per rung tried; open wins
  if it happens, as in v1.

## 9. Cost per attempt (informative; O3)

Per stealth-v2 attempt: one PBKDF2-600k for `perm_key` (shared with
stealth-v1), one permutation of `n` elements, then for each usable rung
tried one STC pass, **one PBKDF2-600k for that rung's `aes_key`**, and one
GCM open. The AES salt is read from each rung's stream, which differs from
rung to rung, so its key cannot be derived once. Worst cases:

| Case | PBKDF2-600k runs | STC passes |
|---|---|---|
| right password, payload at rung `k` | 1 + `k` | `k` |
| wrong password, or no stealth payload | 1 + 5 | 5 |
| plus stealth-v1 fallback | + 1 | + 1 (v1) |

(One less of each for every rung with `L_k < 49`.) The proposal (§3.2)
assumed PBKDF2 runs once per attempt; with this framing it does not.
The runs of different rungs are independent, so a decoder MAY derive
several rungs' keys at once, as long as the lowest rung that opens is the
result (§V2.5.2). The Swift decoder takes the rungs two at a time: a wrong
password is three rounds of wall-clock time instead of five runs in a row,
and a payload at rung `k` costs `1 + min(5, 2 × ceil(k / 2))` runs in
`ceil(k / 2)` rounds.
Stecho's reveal makes one automatic stealth attempt and leaves other
saved passwords to a menu (`AGENTS.md`), so each wrong password costs the
whole worst case. Not yet timed on a phone. For an attacker the same cost
applies per candidate password, unless they estimate the rung from the
carrier's statistics first.

## 10. Threat model summary

On top of the layer (§V2.12), stealth-v2 keeps everything stealth-v1 §9
lists as defended: content confidentiality and authenticity under
AES-256-GCM with a PBKDF2-derived key, no fixed-byte fingerprint (the
stream starts with a random salt), wrong password indistinguishable from
no payload.

What v2 changes:

- **Length:** the stream fills one rung, not the carrier. With the
  password, the rung tells the message size to within 2×. Without it, the
  rung is not readable, only estimable from how many coefficients changed
  (a statistical guess, not measured).
- **Permutation:** unchanged in strength (PBKDF2-600k of the password,
  fixed salt). As in v1 the fixed salt allows one dictionary of
  permutation keys for all Stecho users; the per-message `aes_salt` still
  forces one more PBKDF2 per message, rung and candidate.

Not defended, as in v1: statistical detection of the embedding (layer
§V2.12), transport recompression, forward secrecy (a leaked password
decrypts every past message under it).

## 11. Stability

`stealth-v2` is a draft until the layer's open items that touch the wire
format (O1, O3, O4, O8) are closed; then it is frozen. The info tag
`stecho-stealth-v2-perm` is permanent for this version; an incompatible
change needs `stealth-v3` with a new tag.

## 12. Glossary

| Term | Definition |
|---|---|
| `aes_salt` | The 16-byte AES-key-derivation salt at stream offset 0 |
| `aes_nonce` | The 12-byte AES-GCM nonce at stream offset 16 |
| `perm_key` | PBKDF2 of the password with the fixed v1 permutation salt; seeds the permutation in both versions |
| `info` (v2) | ASCII `"stecho-stealth-v2-perm"`, the keystream tag of this version |
| rung `k`, `L_k` | Rate step and stream size of the layer (§V2.5) |
