import type { ShortformProfile } from '@/lib/api/types';

export function pickDefaultProfileKey(
  profiles: ShortformProfile[],
  canvas: { width: number; height: number },
  defaultProfile: string | null,
): string | undefined {
  const wantPortrait = canvas.height > canvas.width;
  const wantLandscape = canvas.width > canvas.height;
  const matching = profiles.find((profile) =>
    wantPortrait ? profile.height > profile.width : wantLandscape ? profile.width > profile.height : false,
  );
  if (matching) return matching.key;
  if (defaultProfile && profiles.some((profile) => profile.key === defaultProfile)) {
    return defaultProfile;
  }
  return profiles[0]?.key;
}

export function canvasOrientation(
  canvas: { width: number; height: number },
): 'landscape' | 'portrait' | 'square' {
  if (canvas.width > canvas.height) return 'landscape';
  if (canvas.height > canvas.width) return 'portrait';
  return 'square';
}

export function profileOrientationKey(
  profile: Pick<ShortformProfile, 'width' | 'height'>,
): 'exportProfilePortrait' | 'exportProfileLandscape' | 'exportProfileSquare' {
  if (profile.height > profile.width) return 'exportProfilePortrait';
  if (profile.width > profile.height) return 'exportProfileLandscape';
  return 'exportProfileSquare';
}
