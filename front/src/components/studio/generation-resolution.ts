/** Client-facing video resolution tiers. Mirrors
 * `back/app/providers/base.py` `STUDIO_RESOLUTION_TIERS` / `adapt_resolution_tier`
 * so the studio can preview the same downward adaptation the router applies
 * after a model is chosen. Never invent a vendor spelling (`768P`) here. */

export const STUDIO_RESOLUTION_TIERS = ['480p', '720p', '1080p', '2K'] as const;

export type StudioResolutionTier = (typeof STUDIO_RESOLUTION_TIERS)[number];

export type ResolutionAdaptKind = 'exact' | 'downgrade' | 'upgrade';

export type AdaptedStudioResolution = {
  studioTier: StudioResolutionTier;
  kind: ResolutionAdaptKind;
};

export const STUDIO_RESOLUTION_LABEL_KEYS = {
  '480p': 'resolutionSd',
  '720p': 'resolutionHd',
  '1080p': 'resolutionFhd',
  '2K': 'resolution2k',
} as const;

function isStudioTier(value: string): value is StudioResolutionTier {
  return (STUDIO_RESOLUTION_TIERS as readonly string[]).includes(value);
}

export function adaptStudioResolution(
  requested: StudioResolutionTier,
  available: readonly string[] | null | undefined,
): AdaptedStudioResolution {
  if (available == null) {
    return { studioTier: requested, kind: 'exact' };
  }
  const supported = available.filter(isStudioTier);
  if (supported.includes(requested)) {
    return { studioTier: requested, kind: 'exact' };
  }
  const reqIdx = STUDIO_RESOLUTION_TIERS.indexOf(requested);
  for (let index = reqIdx - 1; index >= 0; index -= 1) {
    const tier = STUDIO_RESOLUTION_TIERS[index];
    // `index` is always in range here, but `noUncheckedIndexedAccess` widens
    // the read to `| undefined`, so narrow rather than assert.
    if (tier && supported.includes(tier)) {
      return { studioTier: tier, kind: 'downgrade' };
    }
  }
  const lowest = STUDIO_RESOLUTION_TIERS.find((tier) => supported.includes(tier));
  if (lowest) {
    return { studioTier: lowest, kind: 'upgrade' };
  }
  return { studioTier: requested, kind: 'exact' };
}
