'use client';

import { useCallback } from 'react';

import { NavigationFadeWatcher } from '@/components/layout/navigation-fade-watcher';
import { ThemeProvider } from '@/components/theme/theme-provider';
import { ToastProvider } from '@/components/ui/toast';
import { usePathname } from '@/i18n/navigation';
import type { ThemePreference } from '@/lib/theme';
import { syncThemePreference } from '@/lib/theme-sync';

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
  // stored on the account so it follows them to another device.
  const persistTheme = useCallback(
    (theme: ThemePreference) => syncThemePreference(theme, pathname),
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
