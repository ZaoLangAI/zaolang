'use client';

import { RegionMenu } from '@/components/layout/region-menu';
import { ThemeMenu } from '@/components/layout/theme-menu';

/**
 * The presentation controls, side by side.
 *
 * There is no standalone language switcher: region drives interface
 * language (see `regionLocale`). Signed-in or not, a visitor can pick one —
 * `RegionMenu` writes it to the account when there is one, and to the locale
 * cookie regardless, so an anonymous choice still sticks on the next visit.
 */
export function PreferenceMenu() {
  return (
    <div className="flex items-center gap-1.5">
      <RegionMenu />
      <ThemeMenu />
    </div>
  );
}
