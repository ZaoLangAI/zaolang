const RETRY_DELAYS_MS = [200, 500, 1_000, 2_000] as const;

/**
 * How long to wait before the next `GET .../input-request`.
 *
 * `null` means stop: not a 404 (real error / already answered is the
 * parent's problem), or the panel was unmounted. A 404 while still
 * `awaiting_input` is the emit-before-row race — keep retrying, capped
 * at 2s, until the parent unmounts this panel.
 */
export function inputRequestRetryMs(args: {
  attempt: number;
  isNotFound: boolean;
  cancelled?: boolean;
}): number | null {
  if (args.cancelled || !args.isNotFound) return null;
  if (args.attempt <= 0) return 0;
  const index = Math.min(args.attempt, RETRY_DELAYS_MS.length) - 1;
  return RETRY_DELAYS_MS[index];
}
