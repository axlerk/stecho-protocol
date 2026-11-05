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

`swift-jpeg/os.swift` is the one file of the vendored swift-jpeg 1.1.0 (MPL-2.0,
<https://github.com/kelvin13/jpeg>) that Stecho modified (added Apple-platform
`#if` branches). It is published here for the same reason and under the same
license; the rest of swift-jpeg is available upstream.
