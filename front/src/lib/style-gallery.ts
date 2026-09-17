import type { Locale } from '@/i18n/routing';
import type { StyleGalleryEntry } from '@/lib/api/types';

/** Style gallery labels ship in all three languages so one cached response serves every locale. */
export function styleGalleryLabel(entry: StyleGalleryEntry, locale: Locale): string {
  if (locale === 'en') return entry.label_en;
  if (locale === 'ja') return entry.label_ja;
  return entry.label_zh;
}
