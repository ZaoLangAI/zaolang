/** Margin before a signed GET URL expires at which the player should re-sign. */
export const SIGNED_URL_REFRESH_MARGIN_MS = 60_000;

export function isPlayAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  );
}

export function isNotAllowedError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'NotAllowedError') ||
    (error instanceof Error && error.name === 'NotAllowedError')
  );
}

/**
 * `play()` that does not leak Chrome's play/pause race to the page.
 *
 * Chrome rejects an in-flight `play()` with `AbortError` when `pause()` runs
 * first. That is expected, not a runtime crash.
 */
export async function playMedia(el: HTMLMediaElement): Promise<void> {
  try {
    await el.play();
  } catch (error) {
    if (isPlayAbortError(error)) return;
    throw error;
  }
}

/**
 * Wait for an in-flight `play()` to settle, then pause.
 *
 * Pausing while `play()` is pending is what produces
 * "The play() request was interrupted by a call to pause()".
 */
export async function pauseMedia(
  el: HTMLMediaElement,
  playInFlight: Promise<void> | null | undefined,
): Promise<void> {
  if (playInFlight) {
    try {
      await playInFlight;
    } catch {
      // The pending play may reject for reasons other than abort; we still pause.
    }
  }
  el.pause();
}

/** Origin + path, so two signed URLs for the same object compare equal. */
export function mediaObjectKey(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return url.split('?')[0] ?? url;
  }
}

/**
 * Expiry instant (epoch ms) for an AWS/MinIO SigV4 GET URL.
 *
 * Reads `X-Amz-Date` + `X-Amz-Expires`. Returns null when the URL is not
 * signed that way (or is malformed), so the caller can skip proactive refresh.
 */
export function signedUrlExpiresAt(url: string): number | null {
  try {
    const parsed = new URL(url);
    const date = parsed.searchParams.get('X-Amz-Date');
    const expires = parsed.searchParams.get('X-Amz-Expires');
    if (!date || !expires) return null;
    const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(date);
    if (!match) return null;
    const issued = Date.UTC(
      Number(match[1]),
      Number(match[2]) - 1,
      Number(match[3]),
      Number(match[4]),
      Number(match[5]),
      Number(match[6]),
    );
    const ttlSeconds = Number(expires);
    if (!Number.isFinite(ttlSeconds) || ttlSeconds < 0) return null;
    return issued + ttlSeconds * 1000;
  } catch {
    return null;
  }
}

export function delayUntilSignedUrlRefresh(url: string, now = Date.now()): number | null {
  const expiresAt = signedUrlExpiresAt(url);
  if (expiresAt == null) return null;
  return Math.max(0, expiresAt - now - SIGNED_URL_REFRESH_MARGIN_MS);
}
