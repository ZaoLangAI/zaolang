/**
 * The director's framing sentence: where the camera points inside the
 * panorama, folded into the shot's prompt. The capture itself lives in
 * `components/media/panorama-capture.ts`.
 */

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
