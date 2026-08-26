import { setRequestLocale } from 'next-intl/server';

import { SessionProvider } from '@/components/auth/session-provider';

import { StudioAuthGate } from './studio-auth-gate';

/**
 * The full-screen editor shell, deliberately outside `(site)`: no `TopBar`,
 * `LoginDialog`, `CommandPaletteHost`, or `NotificationToastStack` — every
 * pixel goes to the editor itself, matching the standalone-app feel of the
 * OpenCut layout this route's UI is adapted from.
 */
export default async function StudioLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  return (
    <SessionProvider>
      <StudioAuthGate>
        <div className="h-dvh w-screen overflow-hidden bg-surface">{children}</div>
      </StudioAuthGate>
    </SessionProvider>
  );
}
