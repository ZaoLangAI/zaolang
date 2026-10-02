/**
 * A job's outputs as parallel arrays.
 *
 * The API reports a single result on `output_url` / `output_asset_id` and a
 * multi-result one on `output_urls` / `output_asset_ids` — the plural fields
 * stay null for the common single-output job. Reading only the plural pair
 * silently shows nothing for almost every job, which is exactly the bug the
 * canvas workbench shipped with before this was shared.
 *
 * Written out three times already (`inline-image-result.tsx`,
 * `existing-asset-picker-dialog.tsx`, and the workbench) before being pulled
 * here.
 */
export interface JobOutputs {
  urls: string[];
  assetIds: string[];
}

export function jobOutputs(
  job: {
    output_url?: string | null;
    output_urls?: string[] | null;
    output_asset_id?: string | null;
    output_asset_ids?: string[] | null;
  } | null,
): JobOutputs {
  if (!job) return { urls: [], assetIds: [] };
  return {
    urls: job.output_urls?.length ? job.output_urls : job.output_url ? [job.output_url] : [],
    assetIds: job.output_asset_ids?.length
      ? job.output_asset_ids
      : job.output_asset_id
        ? [job.output_asset_id]
        : [],
  };
}

/**
 * How short a succeeded multi-pass image job came up, or `null` when it
 * delivered everything it was priced for.
 *
 * A character job with several views, or a scene variant set, makes one
 * image per pass; if a later pass fails after earlier ones delivered, the
 * backend keeps those images and settles per image instead of failing the
 * whole job (`requested_outputs` is what it was priced for).
 */
export function partialDelivery(job: {
  status: string;
  requested_outputs?: number | null;
  output_asset_id?: string | null;
  output_asset_ids?: string[] | null;
}): { delivered: number; requested: number } | null {
  const requested = job.requested_outputs ?? 1;
  if (job.status !== 'succeeded' || requested <= 1) return null;
  const delivered = jobOutputs(job).assetIds.length;
  return delivered > 0 && delivered < requested ? { delivered, requested } : null;
}
