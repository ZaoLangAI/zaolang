/**
 * Fields a studio should restore when the author picks a past generation
 * from the version-history strip. `GenerationJobResponse.prompt` is the
 * prompt that was submitted with that job (after client-side polish, if
 * they accepted it) — not the frozen `Draft.params.prompt` from the first
 * create, and not the planner-enhanced text sent to the provider.
 */

export function promptFromVersion(job: { prompt?: string | null }): string | null {
  const prompt = job.prompt?.trim();
  return prompt ? prompt : null;
}

export function durationFromVersion(
  job: { duration_seconds?: number | null },
  allowed: readonly number[],
): number | null {
  const duration = job.duration_seconds;
  return typeof duration === 'number' && allowed.includes(duration) ? duration : null;
}

export function videoAssetKindFromVersion<T extends string>(
  job: { video_asset_kind?: string | null },
  allowed: readonly T[],
): T | null {
  const kind = job.video_asset_kind;
  return typeof kind === 'string' && (allowed as readonly string[]).includes(kind)
    ? (kind as T)
    : null;
}
