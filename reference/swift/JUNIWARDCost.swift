// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//
// Swift port of `conseal.juniward._costmap.compute_cost` from conseal
// (https://github.com/uibk-uncover/conseal, MPL-2.0). This file stays under
// the MPL; its Source Code Form is published at
// https://github.com/axlerk/stecho-protocol/tree/main/reference/swift
// (mirrored from this file by .github/workflows/sync-spec.yml).

import Foundation

/// J-UNIWARD content-adaptive distortion cost map.
///
/// Direct port of `conseal.juniward._costmap.compute_cost` (which in turn
/// ports the Binghamton MATLAB reference). For each AC DCT coefficient
/// in the carrier, returns the cost of changing it by ±1 — STC consumes
/// this map to pick the lowest-cost embedding satisfying the syndrome
/// constraint.
///
/// Reference:
/// V. Holub, J. Fridrich, T. Denemark.
/// "Universal distortion function for steganography in an arbitrary domain."
/// EURASIP Journal on Information Security, 2014.
/// DOI: 10.1186/1687-417X-2014-1
///
/// Frozen parameters per `spec/juniward-layer.md` §3:
/// - Wavelet: Daubechies-8 (`db8`), 3 directional sub-bands (LH, HL, HH)
/// - Stabilization σ = 2⁻⁶ = 0.015625
/// - Implementation: JUNIWARD_ORIGINAL (the 2014 paper's variant; the
///   fix-off-by-one variant from the 2023 errata is not used in v1)
///
/// Performance note: this is a correctness-first Swift port. It mirrors
/// conseal's numpy code with naive nested loops. On Apple Silicon the
/// 256×256 case takes ~few seconds. Phase C2.1 will optimise the hot
/// inner loops with Accelerate / vDSP; not implemented yet because we
/// want a verified-correct baseline first.
public enum JUNIWARDCost {

    // MARK: - Frozen parameters

    public static let sigma: Double = 1.0 / 64.0   // 2^-6

    public enum Implementation {
        /// The original 2014 paper variant (matches conseal's
        /// `JUNIWARD_ORIGINAL` constant and the DDE/Binghamton MATLAB
        /// reference).
        case juniwardOriginal
    }

    public enum CostError: Error {
        case nonMultipleOfEight(width: Int, height: Int)
        case shapeMismatch(detail: String)
    }

    // MARK: - 2D index helpers

    /// 4D index helper for the cost output. Indexed as
    /// `(blockY, blockX, dctRow, dctCol)` where `dctRow` and `dctCol` are
    /// the row/col inside an 8×8 DCT block in natural order (not zigzag).
    /// Use `costMap[by, bx, r, c]` to read; the underlying storage is a
    /// flat row-major array.
    public struct CostMap {
        public let blocksY: Int
        public let blocksX: Int
        @usableFromInline internal var storage: [Double]

        public init(blocksY: Int, blocksX: Int) {
            self.blocksY = blocksY
            self.blocksX = blocksX
            self.storage = [Double](repeating: 0, count: blocksY * blocksX * 64)
        }

        public subscript(by: Int, bx: Int, r: Int, c: Int) -> Double {
            get {
                storage[((by * blocksX + bx) * 8 + r) * 8 + c]
            }
            set {
                storage[((by * blocksX + bx) * 8 + r) * 8 + c] = newValue
            }
        }
    }

    // MARK: - Public entry

    /// Compute the J-UNIWARD cost map for a single channel.
    ///
    /// - Parameters:
    ///   - spatial: decompressed pixel array, `[height][width]` of `Double`
    ///     values (typically obtained by IDCT-decoding the cover JPEG).
    ///     `height` and `width` must each be multiples of 8.
    ///   - quantTable: 8×8 luminance quantization table from the carrier
    ///     JPEG, as `Double` values. Use the matching table for whichever
    ///     plane (Y / Cb / Cr) is being analysed.
    /// - Returns: A `CostMap` with shape `(blocksY, blocksX, 8, 8)`. The
    ///   cost at `(by, bx, r, c)` is the cost of changing the DCT
    ///   coefficient at natural-order `(r, c)` of block `(by, bx)` by ±1.
    public static func compute(
        spatial: [[Double]],
        quantTable: [[Double]],
        implementation: Implementation = .juniwardOriginal
    ) throws -> CostMap {
        guard let firstRow = spatial.first else {
            throw CostError.shapeMismatch(detail: "spatial array is empty")
        }
        let height = spatial.count
        let width = firstRow.count
        guard height > 0, width > 0, height % 8 == 0, width % 8 == 0 else {
            throw CostError.nonMultipleOfEight(width: width, height: height)
        }
        guard quantTable.count == 8, quantTable.allSatisfy({ $0.count == 8 }) else {
            throw CostError.shapeMismatch(detail: "quantTable must be 8x8")
        }
        for row in spatial where row.count != width {
            throw CostError.shapeMismatch(detail: "spatial rows have inconsistent width")
        }

        let blocksY = height / 8
        let blocksX = width / 8

        // 1. Daubechies-8 filters: (hpdf, lpdf) and 3 2D filter kernels.
        let filters2D = Daubechies8.filters2D    // [3][16][16]
        let filterSize = 16

        // 2. Spatial impact: for each DCT (r, c), compute the 8×8 pixel
        //    patch that flipping that DCT coefficient by ±1 produces,
        //    scaled by the quantization step.
        let spatialImpact = computeSpatialImpact(quantTable: quantTable)  // [8][8][8][8]

        // 3. Wavelet impact: |correlate2d(spatial_impact, filters[k],
        //    mode=full, fill=0)| for each filter and each (r, c).
        //    Shape: [3][8][8][23][23] where 23 = 8 + 16 - 1.
        let waveletImpact = computeWaveletImpact(
            spatialImpact: spatialImpact, filters: filters2D
        )

        // 4. Symmetric-pad the cover spatial image by `filterSize` pixels
        //    on each side, then correlate with each filter (mode='same').
        //    The resulting reference_covers are cropped to the
        //    JUNIWARD_ORIGINAL crop window.
        let padded = symmetricPad(spatial, padSize: filterSize)
        var referenceCovers: [[[Double]]] = []   // [3][rcHeight][rcWidth]
        referenceCovers.reserveCapacity(3)
        for k in 0..<3 {
            let full = correlate2DSame(padded, kernel: filters2D[k])
            // Crop per JUNIWARD_ORIGINAL: rc[pad-7 : height+8+pad, pad-7 : width+8+pad].
            let cropped = cropReferenceCover(
                full,
                padSize: filterSize,
                height: height, width: width
            )
            referenceCovers.append(cropped)
        }

        // 5. For each 8×8 block, slide a 23×23 window over each
        //    reference cover, weight by reciprocal of (|window| + σ),
        //    and accumulate over the wavelet_impact tensor.
        var costs = CostMap(blocksY: blocksY, blocksX: blocksX)
        let windowSize = 8 + filterSize - 1   // = 23
        for by in 0..<blocksY {
            for bx in 0..<blocksX {
                // The 23×23 window starts at offset (by*8, bx*8) in the
                // cropped reference cover (stride=8 over the cover).
                for k in 0..<3 {
                    let rc = referenceCovers[k]
                    var reciprocal = [[Double]](
                        repeating: [Double](repeating: 0, count: windowSize),
                        count: windowSize
                    )
                    for wy in 0..<windowSize {
                        let rowAbs = rc[by * 8 + wy]
                        for wx in 0..<windowSize {
                            reciprocal[wy][wx] = 1.0 / (abs(rowAbs[bx * 8 + wx]) + sigma)
                        }
                    }
                    // Accumulate per DCT-coefficient cost contribution.
                    let wiK = waveletImpact[k]
                    for r in 0..<8 {
                        for c in 0..<8 {
                            let wi = wiK[r][c]
                            var acc: Double = 0
                            for wy in 0..<windowSize {
                                let wiRow = wi[wy]
                                let recRow = reciprocal[wy]
                                for wx in 0..<windowSize {
                                    acc += wiRow[wx] * recRow[wx]
                                }
                            }
                            costs[by, bx, r, c] += acc
                        }
                    }
                }
            }
        }
        return costs
    }

    // MARK: - Step 2: spatial impact

    /// `spatialImpact[r][c]` is the 8×8 pixel patch obtained by IDCT-ing
    /// a DCT block that is `qt[r][c]` at index `(r, c)` and zero elsewhere.
    /// (Equivalent to "a unit step in coefficient `(r, c)` after
    /// dequantization", which is what a ±1 flip of the quantized
    /// coefficient produces.)
    @usableFromInline
    internal static func computeSpatialImpact(
        quantTable: [[Double]]
    ) -> [[[[Double]]]] {
        var result = [[[[Double]]]](
            repeating: [[[Double]]](
                repeating: [[Double]](repeating: [Double](repeating: 0, count: 8), count: 8),
                count: 8
            ),
            count: 8
        )
        var unit = [[Double]](repeating: [Double](repeating: 0, count: 8), count: 8)
        for r in 0..<8 {
            for c in 0..<8 {
                unit[r][c] = 1
                let patch = DCT8x8.inverse(unit)
                unit[r][c] = 0
                let q = quantTable[r][c]
                for py in 0..<8 {
                    for px in 0..<8 {
                        result[r][c][py][px] = patch[py][px] * q
                    }
                }
            }
        }
        return result
    }

    // MARK: - Step 3: wavelet impact

    @usableFromInline
    internal static func computeWaveletImpact(
        spatialImpact: [[[[Double]]]],
        filters: [[[Double]]]
    ) -> [[[[[Double]]]]] {   // [3][8][8][23][23]
        let windowSize = 8 + filters[0].count - 1
        var result = [[[[[Double]]]]](
            repeating: [[[[Double]]]](
                repeating: [[[Double]]](
                    repeating: [[Double]](
                        repeating: [Double](repeating: 0, count: windowSize),
                        count: windowSize
                    ),
                    count: 8
                ),
                count: 8
            ),
            count: filters.count
        )
        for k in 0..<filters.count {
            let kernel = filters[k]
            for r in 0..<8 {
                for c in 0..<8 {
                    let full = correlate2DFull(spatialImpact[r][c], kernel: kernel)
                    for y in 0..<windowSize {
                        let row = full[y]
                        for x in 0..<windowSize {
                            result[k][r][c][y][x] = abs(row[x])
                        }
                    }
                }
            }
        }
        return result
    }

    // MARK: - Symmetric padding

    /// Symmetric-pad `arr` by `padSize` rows/columns on each side, using
    /// reflect-without-edge semantics matching numpy's `mode='symmetric'`:
    /// the boundary row/column is included in the reflection (so the
    /// edge pattern reads `d c b a | a b c d`).
    @usableFromInline
    internal static func symmetricPad(_ arr: [[Double]], padSize: Int) -> [[Double]] {
        let h = arr.count
        let w = arr[0].count
        let H = h + 2 * padSize
        let W = w + 2 * padSize
        var out = [[Double]](repeating: [Double](repeating: 0, count: W), count: H)
        for y in 0..<H {
            let srcY = mirrorIndex(y - padSize, length: h)
            let src = arr[srcY]
            for x in 0..<W {
                let srcX = mirrorIndex(x - padSize, length: w)
                out[y][x] = src[srcX]
            }
        }
        return out
    }

    /// Numpy `symmetric` reflection index: idx is reflected at boundaries
    /// without repeating the edge (so `mirrorIndex(-1, 4) == 0`,
    /// `mirrorIndex(-2, 4) == 1`).
    @usableFromInline
    internal static func mirrorIndex(_ idx: Int, length: Int) -> Int {
        precondition(length > 0)
        let period = 2 * length
        var k = idx % period
        if k < 0 { k += period }
        return k < length ? k : period - 1 - k
    }

    // MARK: - 2D correlation
    //
    // scipy.signal.correlate2d uses the following indexing convention,
    // which differs subtly from textbook correlation:
    //
    //   correlate2d_full(a, k)[m, n] =
    //       sum_{p, q} a[m - (Nb-1) + p, n - (Mb-1) + q] * k[p, q]
    //
    //   correlate2d_same(a, k)[m, n] =
    //       correlate2d_full(a, k)[m + Nb//2, n + Mb//2]
    //     = sum_{p, q} a[m - (Nb-1-Nb//2) + p, n - ...] * k[p, q]
    //
    // For even Nb (our 16-tap Daubechies-8 filters), the "same" offset
    // is `(Nb-1) - (Nb//2) = 7` per axis. The kernel is NOT flipped:
    // the formula is standard correlation with output index shifted.

    /// scipy-style 2D cross-correlation, `mode='same'`. Same shape as `a`,
    /// zero-fill boundary.
    @usableFromInline
    internal static func correlate2DSame(_ a: [[Double]], kernel: [[Double]]) -> [[Double]] {
        let h = a.count
        let w = a[0].count
        let kh = kernel.count
        let kw = kernel[0].count
        let yOffset = (kh - 1) - (kh / 2)   // = 7 for kh=16, 0 for kh=2
        let xOffset = (kw - 1) - (kw / 2)
        var out = [[Double]](repeating: [Double](repeating: 0, count: w), count: h)
        for y in 0..<h {
            for x in 0..<w {
                var acc: Double = 0
                for ky in 0..<kh {
                    let ay = y - yOffset + ky
                    guard ay >= 0, ay < h else { continue }
                    let aRow = a[ay]
                    let kRow = kernel[ky]
                    for kx in 0..<kw {
                        let ax = x - xOffset + kx
                        guard ax >= 0, ax < w else { continue }
                        acc += aRow[ax] * kRow[kx]
                    }
                }
                out[y][x] = acc
            }
        }
        return out
    }

    /// scipy-style 2D cross-correlation, `mode='full'`. Output shape
    /// `(h + kh - 1, w + kw - 1)`. Zero-fill boundary.
    @usableFromInline
    internal static func correlate2DFull(_ a: [[Double]], kernel: [[Double]]) -> [[Double]] {
        let h = a.count
        let w = a[0].count
        let kh = kernel.count
        let kw = kernel[0].count
        let outH = h + kh - 1
        let outW = w + kw - 1
        var out = [[Double]](repeating: [Double](repeating: 0, count: outW), count: outH)
        for y in 0..<outH {
            for x in 0..<outW {
                var acc: Double = 0
                for ky in 0..<kh {
                    let ay = y - (kh - 1) + ky
                    guard ay >= 0, ay < h else { continue }
                    let aRow = a[ay]
                    let kRow = kernel[ky]
                    for kx in 0..<kw {
                        let ax = x - (kw - 1) + kx
                        guard ax >= 0, ax < w else { continue }
                        acc += aRow[ax] * kRow[kx]
                    }
                }
                out[y][x] = acc
            }
        }
        return out
    }

    // MARK: - Reference cover crop

    /// Crop the full mode='same' reference-cover to the JUNIWARD_ORIGINAL
    /// window: rows `[padSize-7, height+8+padSize)`, cols
    /// `[padSize-7, width+8+padSize)`. Result has shape
    /// `(blocksY*8 + 15, blocksX*8 + 15)` = the sliding-window cover
    /// region for the cost computation.
    @usableFromInline
    internal static func cropReferenceCover(
        _ rc: [[Double]],
        padSize: Int,
        height: Int,
        width: Int
    ) -> [[Double]] {
        let yStart = padSize - 7
        let yEnd = height + 8 + padSize
        let xStart = padSize - 7
        let xEnd = width + 8 + padSize
        var cropped = [[Double]]()
        cropped.reserveCapacity(yEnd - yStart)
        for y in yStart..<yEnd {
            let row = rc[y]
            cropped.append(Array(row[xStart..<xEnd]))
        }
        return cropped
    }
}

// MARK: - Daubechies-8 wavelet filter bank

/// Frozen Daubechies-8 filter coefficients matching conseal's
/// `tools.spatial.daubechies8()`. The values come from the standard db8
/// orthogonal-wavelet definition. Both filters have length 16; the
/// outer-product combinations yield the three 16×16 2D directional
/// filters J-UNIWARD uses (LH, HL, HH).
@usableFromInline
internal enum Daubechies8 {
    /// 1D high-pass decomposition filter, paper notation `g`.
    @usableFromInline
    static let highPass: [Double] = [
        -0.0544158422, +0.3128715909, -0.6756307363, +0.5853546837,
        +0.0158291053, -0.2840155430, -0.0004724846, +0.1287474266,
        +0.0173693010, -0.0440882539, -0.0139810279, +0.0087460940,
        +0.0048703530, -0.0003917404, -0.0006754494, -0.0001174768,
    ]

    /// 1D low-pass decomposition filter, paper notation `h`. Derived
    /// from `g` per the standard QMF relation: `h[i] = (-1)^i * g[N-1-i]`.
    @usableFromInline
    static let lowPass: [Double] = {
        let g = Daubechies8.highPass
        let n = g.count
        var out = [Double](repeating: 0, count: n)
        for i in 0..<n {
            let sign: Double = (i % 2 == 0) ? 1 : -1
            out[i] = sign * g[n - 1 - i]
        }
        return out
    }()

    /// Three 16×16 2D filters:
    /// - `filters2D[0]` = lpdf ⊗ hpdf  (LH — horizontal high-pass)
    /// - `filters2D[1]` = hpdf ⊗ lpdf  (HL — vertical high-pass)
    /// - `filters2D[2]` = hpdf ⊗ hpdf  (HH — diagonal)
    @usableFromInline
    static let filters2D: [[[Double]]] = {
        let g = Daubechies8.highPass
        let h = Daubechies8.lowPass
        return [
            outer(h, g),
            outer(g, h),
            outer(g, g),
        ]
    }()

    /// Outer product of two 1D vectors `a` and `b`: result `[i, j] = a[i] * b[j]`.
    private static func outer(_ a: [Double], _ b: [Double]) -> [[Double]] {
        var out = [[Double]](repeating: [Double](repeating: 0, count: b.count), count: a.count)
        for i in 0..<a.count {
            let ai = a[i]
            for j in 0..<b.count {
                out[i][j] = ai * b[j]
            }
        }
        return out
    }
}

// MARK: - 8×8 inverse DCT

/// Naive 8×8 inverse DCT (Type-II) matching numpy / scipy `idct(idct(x.T,
/// norm='ortho').T, norm='ortho')` semantics — i.e. orthonormal 2D IDCT.
///
/// Used by J-UNIWARD to compute the spatial-domain "impact" of a unit
/// step in a single DCT coefficient. Output is the inverse-DCT of the
/// unit vector at position (r, c), scaled by quantization at apply time.
///
/// This is the simplest possible implementation (matrix multiplication
/// against precomputed cosine bases). For ~1024 calls per cost map it's
/// not the bottleneck; the wavelet-impact correlate2DFull and the cost
/// inner loop dominate.
@usableFromInline
internal enum DCT8x8 {

    /// Precomputed orthonormal IDCT basis: `basis[k][n]` = the n-th sample
    /// of the k-th DCT basis function. Multiplying a coefficient vector
    /// `C[k]` against this matrix recovers the spatial signal.
    @usableFromInline
    static let basis: [[Double]] = {
        var m = [[Double]](repeating: [Double](repeating: 0, count: 8), count: 8)
        let alpha0 = 1.0 / sqrt(8.0)
        let alpha = sqrt(2.0 / 8.0)
        let pi = Double.pi
        for k in 0..<8 {
            let scale = (k == 0) ? alpha0 : alpha
            for n in 0..<8 {
                m[k][n] = scale * cos(pi * Double(k) * (Double(n) + 0.5) / 8.0)
            }
        }
        return m
    }()

    /// 2D orthonormal IDCT. Returns an 8×8 spatial-domain block.
    @usableFromInline
    static func inverse(_ block: [[Double]]) -> [[Double]] {
        precondition(block.count == 8 && block[0].count == 8)
        // First IDCT along columns: temp[k1][n2] = sum_{k2} block[k1][k2] * basis[k2][n2]
        var temp = [[Double]](repeating: [Double](repeating: 0, count: 8), count: 8)
        for k1 in 0..<8 {
            let row = block[k1]
            for n2 in 0..<8 {
                var s: Double = 0
                for k2 in 0..<8 {
                    s += row[k2] * basis[k2][n2]
                }
                temp[k1][n2] = s
            }
        }
        // Then IDCT along rows: result[n1][n2] = sum_{k1} temp[k1][n2] * basis[k1][n1]
        var result = [[Double]](repeating: [Double](repeating: 0, count: 8), count: 8)
        for n1 in 0..<8 {
            for n2 in 0..<8 {
                var s: Double = 0
                for k1 in 0..<8 {
                    s += temp[k1][n2] * basis[k1][n1]
                }
                result[n1][n2] = s
            }
        }
        return result
    }
}
