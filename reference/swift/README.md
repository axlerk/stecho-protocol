# Swift cost-map port (MPL-2.0)

`JUNIWARDCost.swift` is the Swift port of conseal's J-UNIWARD cost map that the
Stecho app uses when embedding. It is **not stored in this directory in the
source tree**: `.github/workflows/sync-spec.yml` copies
`StechoCore/JUNIWARDCost.swift` here when it mirrors the spec to the public
`stecho-protocol` repository, so the published file is always the shipped one.

The file is a derivative of [conseal](https://github.com/uibk-uncover/conseal)
and remains under the Mozilla Public License 2.0 (see `LICENSE-MPL-2.0`). It is
only needed to *encode*; decoding a Stecho message never uses costs (see
`../../juniward-layer.md`).

`swift-jpeg/decode.swift` and `swift-jpeg/encode.swift` are the two files of
the vendored swift-jpeg 1.1.0 (MPL-2.0, <https://github.com/kelvin13/jpeg>)
that Stecho modified; each change is marked "Patched for Stecho" in the file.

- `decode.swift`: the first scan grows the image only when the frame header's
  height is 0 (upstream grew it for every file, so a small crafted JPEG could
  allocate gigabytes of coefficients); a height redefinition (DNL) segment is
  refused; progressive restart intervals clamp both ends of the row range, and
  intervals that start past the last block are not decoded.
- `encode.swift`: the whole file is wrapped in `#if DEBUG`. The app does not
  encode with swift-jpeg; only a test helper does.

They are published here for the same reason and under the same license; the
rest of swift-jpeg is unmodified and available upstream. One upstream file,
`os.swift` (file input and output, never called by Stecho), was removed from
the app on 2026-11-15 and is no longer published here.
