'use client';

import { useEffect } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { useRouter } from '@/i18n/navigation';

/**
 * This route has no `LoginDialog` (no site chrome at all), so a session that
 * resolves to anonymous — an expired refresh cookie, a link opened cold —
 * has nowhere to sign back in from. Bounce to the site root instead of
 * leaving the editor stuck showing a permanent load error.
 */
export function StudioAuthGate({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'anonymous') router.replace('/');
  }, [status, router]);

  if (status === 'anonymous') return null;
  return <>{children}</>;
}
