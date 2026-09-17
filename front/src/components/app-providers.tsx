'use client';

import { useCallback } from 'react';

import { NavigationFadeWatcher } from '@/components/layout/navigation-fade-watcher';
import { ThemeProvider } from '@/components/theme/theme-provider';
import { ToastProvider } from '@/components/ui/toast';
import { usePathname } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import type { ThemePreference } from '@/lib/theme';

const ADMIN_PATH = /(?:^|\/)admin(?:\/|$)/;

export function AppProviders({
  children,
  initialPreference,
  initialReduceMotion,
}: {
  children: React.ReactNode;
  initialPreference: ThemePreference;
  initialReduceMotion: boolean;
}) {
  const pathname = usePathname();

  // Signed-out users keep the choice in a cookie; signed-in users also get it
  // stored on the account so it follows them to another device. A failed write
  // is not worth interrupting the user over. Console routes must not touch the
  // consumer preferences API — that 401 would redeem `/v1/auth/refresh`.
  const persistTheme = useCallback(
    (theme: ThemePreference) => {
      if (ADMIN_PATH.test(pathname)) return;
      void api
        .patch('/v1/auth/me/preferences', { theme }, { anonymous: true })
        .catch(() => undefined);
    },
    [pathname],
  );

  return (
    <ThemeProvider
      initialPreference={initialPreference}
      initialReduceMotion={initialReduceMotion}
      onPersist={persistTheme}
    >
      <NavigationFadeWatcher />
      <ToastProvider>{children}</ToastProvider>
    </ThemeProvider>
  );
}
