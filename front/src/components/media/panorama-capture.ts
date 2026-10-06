/**
 * Turning a framed panorama view into a still: the canvas director composes
 * character cut-outs over it, the scene workspace's 全景 slot cuts a posed
 * shot out of it (AC-7). Pair with `panorama-viewer.tsx`'s `captureCanvas`.
 */

/** Where a character cut-out sits over the viewport, in fractions of it, so a
 * placement survives the viewer being resized. */
export interface CharacterPlacement {
  id: string;
  skillId: string;
  url: string;
  /** Centre, 0–1 across the viewport. */
  x: number;
  y: number;
  /** Height as a fraction of the viewport. */
  scale: number;
}

/**
 * Composites the rendered panorama view and the character cut-outs into one
 * still.
 *
 * Drawn onto a fresh 2D canvas rather than read straight from the WebGL one:
 * the overlays are ordinary DOM images positioned over the viewer, so they
 * exist nowhere in the GL buffer and have to be painted in at the same
 * relative positions the user placed them.
 */
export async function composeShot(
  source: HTMLCanvasElement,
  placements: CharacterPlacement[],
): Promise<Blob> {
  const out = document.createElement('canvas');
  out.width = source.width;
  out.height = source.height;
  const ctx = out.getContext('2d');
  if (!ctx) throw new Error('no-2d-context');
  ctx.drawImage(source, 0, 0);

  for (const placement of placements) {
    const image = await loadImage(placement.url).catch(() => null);
    // One unreachable cut-out must not lose the whole frame the user just
    // set up; the rest of the shot is still worth having.
    if (!image) continue;
    const height = out.height * placement.scale;
    const width = image.naturalWidth ? height * (image.naturalWidth / image.naturalHeight) : height;
    ctx.drawImage(
      image,
      placement.x * out.width - width / 2,
      placement.y * out.height - height / 2,
      width,
      height,
    );
  }

  return new Promise<Blob>((resolve, reject) => {
    out.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('encode-failed'))), 'image/png');
  });
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    // The signed URLs come from our own object storage on another origin; the
    // canvas would otherwise be tainted and `toBlob` would throw.
    image.crossOrigin = 'anonymous';
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('load-failed'));
    image.src = url;
  });
}
