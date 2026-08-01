'use client';

import { useCallback } from 'react';

import { SessionProvider } from '@/components/auth/session-provider';
import { ThemeProvider } from '@/components/theme/theme-provider';
import { ToastProvider } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import type { ThemePreference } from '@/lib/theme';

export function AppProviders({
  children,
  initialPreference,
  initialReduceMotion,
}: {
  children: React.ReactNode;
  initialPreference: ThemePreference;
  initialReduceMotion: boolean;
}) {
  // Signed-out users keep the choice in a cookie; signed-in users also get it
  // stored on the account so it follows them to another device. A failed write
  // is not worth interrupting the user over.
  const persistTheme = useCallback((theme: ThemePreference) => {
    void api.patch('/v1/auth/me/preferences', { theme }).catch(() => undefined);
  }, []);

  return (
    <ThemeProvider
      initialPreference={initialPreference}
      initialReduceMotion={initialReduceMotion}
      onPersist={persistTheme}
    >
      <SessionProvider>
        <ToastProvider>{children}</ToastProvider>
      </SessionProvider>
    </ThemeProvider>
  );
}
