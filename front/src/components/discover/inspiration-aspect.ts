/**
 * Tile shape for the inspiration wall, derived from the cover's own pixels.
 *
 * The wall is a masonry layout, so a tile's height is what places it. Taking
 * that from the cover means the image is never cropped to a shape it was not
 * made in — but an outlier would also be free to occupy a whole column, so the
 * extremes are clamped rather than trusted.
 */

/**
 * Widest and tallest tile the wall will render, as width over height. The
 * bounds are the extremes the product actually produces — cinemascope and
 * full-bleed vertical — so nothing in the catalogue gets cropped by them.
 */
const WIDEST = 21 / 9;
const TALLEST = 9 / 16;

/** What a cover of unknown size falls back to, matching `WorkCard`. */
const FALLBACK = 16 / 9;

export function tileRatio(width?: number | null, height?: number | null): number {
  if (!width || !height) return FALLBACK;
  return Math.min(WIDEST, Math.max(TALLEST, width / height));
}

/** Representative shapes, in the order the skeleton cycles through them. */
export const TILE_RATIO_SAMPLES = [21 / 9, 16 / 9, 9 / 16, 1] as const;
