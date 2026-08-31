/**
 * RFC 4122 UUID v4 that also works on an HTTP (non-secure) origin.
 *
 * `crypto.randomUUID` is a secure-context-only API. Production is served on
 * `http://<public-ip>` (`COOKIE_SECURE=false`), so `window.isSecureContext`
 * is false and `crypto.randomUUID` is undefined — every write that minted an
 * Idempotency-Key (or any other client id) threw before the request left the
 * browser. `getRandomValues` is available on HTTP; fall back to it, then to
 * `Math.random` only if even that is missing (non-browser tests).
 */
export function randomUuid(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (typeof cryptoApi?.getRandomValues === 'function') {
    cryptoApi.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  const version = bytes[6] ?? 0;
  const variant = bytes[8] ?? 0;
  bytes[6] = (version & 0x0f) | 0x40;
  bytes[8] = (variant & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
