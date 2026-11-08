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

`swift-jpeg/os.swift` and `swift-jpeg/decode.swift` are the two files of the
vendored swift-jpeg 1.1.0 (MPL-2.0, <https://github.com/kelvin13/jpeg>) that
Stecho modified: `os.swift` gained Apple-platform `#if` branches, and
`decode.swift` lets the first scan grow the image only when the frame header's
height is 0 (upstream grew it for every file, so a small crafted JPEG could
allocate gigabytes of coefficients; the change is marked "Patched for Stecho"
in the file). They are published here for the same reason and under the same
license; the rest of swift-jpeg is available upstream.
