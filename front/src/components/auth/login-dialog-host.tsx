'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';

const LoginDialog = dynamic(
  () => import('@/components/auth/login-dialog').then((mod) => mod.LoginDialog),
  { ssr: false },
);

/**
 * Defers the login-dialog chunk until the first `openLogin` / `requireAuth`
 * so every consumer page does not pay for the form on first paint.
 */
export function LoginDialogHost() {
  const { loginPrompt } = useSession();
  const [ready, setReady] = useState(false);

  // Latch during render: once the dialog has been asked for, keep it mounted
  // so its close animation and form state survive later toggles.
  if (loginPrompt.open && !ready) setReady(true);

  if (!ready) return null;
  return <LoginDialog />;
}
