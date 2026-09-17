import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { SettingsShell } from '@/components/settings/settings-shell';
import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Me } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('settingsPage');
  return { title: t('title'), description: t('subtitle') };
}

export default async function SettingsPage() {
  const t = await getTranslations('settingsPage');
  const me = await serverFetchOrNull<Me>('/v1/auth/me', { authenticated: true });
  if (!me?.profile) return <SignInPrompt />;

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-8 sm:px-6">
      <BackLink href="/profile">{t('backToProfile')}</BackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />

      <SettingsShell me={me} />
    </div>
  );
}
