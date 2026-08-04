'use client';

import { useSession } from '@/components/auth/session-provider';
import { RegionMenu } from '@/components/layout/region-menu';
import { ThemeMenu } from '@/components/layout/theme-menu';

/**
 * The presentation controls, side by side.
 *
 * There is no standalone language switcher: region drives interface
 * language (see `regionLocale`), so region only appears when signed in — it
 * is stored on the account, and for an anonymous visitor the control would
 * have nowhere to write to.
 */
export function PreferenceMenu() {
  const { user } = useSession();

  return (
    <div className="flex items-center gap-1.5">
      {user ? <RegionMenu /> : null}
      <ThemeMenu />
    </div>
  );
}
