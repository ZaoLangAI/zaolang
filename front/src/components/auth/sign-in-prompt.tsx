'use client';

import { useTranslations } from 'next-intl';

import { useSession } from '@/components/auth/session-provider';
import { Button } from '@/components/ui/button';
import { IconLock } from '@/components/ui/icons';
import { EmptyState } from '@/components/ui/primitives';

/**
 * Shown where a server render found no session.
 *
 * A dialog rather than a redirect to a login route: the user stays on the page
 * they asked for, and it reappears with data as soon as they sign in.
 */
export function SignInPrompt({ description }: { description?: string }) {
  const t = useTranslations('auth');
  const { openLogin } = useSession();

  return (
    <div className="mx-auto w-full max-w-[1160px] px-4 py-20 sm:px-6">
      <EmptyState
        icon={<IconLock className="size-6" />}
        title={t('signInTitle')}
        description={description ?? t('signInSubtitle')}
        action={<Button onClick={openLogin}>{t('signIn')}</Button>}
      />
    </div>
  );
}
