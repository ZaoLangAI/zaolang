import type { BadgeTone } from '@/components/ui/primitives';

/**
 * `behind_the_scenes` -> `BehindTheScenes`. Used to turn a snake_case backend
 * enum value (episode kind, content-link role, content type, episode status)
 * into the suffix of its i18n key, e.g. `t('role' + pascalCase(role))`.
 */
export function pascalCase(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}

export function episodeStatusTone(status: string): BadgeTone {
  if (status === 'published') return 'success';
  if (status === 'production') return 'amber';
  return 'neutral';
}
