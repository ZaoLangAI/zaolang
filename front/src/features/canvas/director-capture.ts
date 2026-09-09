/**
 * Turning a framed panorama view into a still that a generation can use.
 *
 * This module only ever *consumes* a panorama the user supplied. Generating
 * one is not offered: `_IMAGE_SIZE_BY_ASPECT` in
 * `back/app/providers/aihubmix_media.py` has no 2:1 entry and falls back to
 * 1024x1024, so a request for an equirectangular image would quietly come back
 * square. Build that path when a real 2:1 size has been verified against a
 * live credential, not before.
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

/** Human-readable framing, folded into the shot's prompt alongside the lens
 * settings so the model is told where the camera is pointing, not just what
 * glass it is using. */
export function describeFraming(position: { yaw: number; pitch: number; fov: number }): string {
  const vertical =
    position.pitch > 12
      ? 'camera tilted upward, low-angle framing looking up at the subject'
      : position.pitch < -12
        ? 'camera tilted downward, high-angle framing looking down on the subject'
        : 'camera at eye level, horizon near the middle of the frame';
  const breadth =
    position.fov >= 80
      ? 'wide field of view taking in much of the surrounding environment'
      : position.fov <= 40
        ? 'narrow field of view, tightly framed on the subject'
        : 'moderate field of view balancing subject and surroundings';
  return `${vertical}, ${breadth}`;
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
