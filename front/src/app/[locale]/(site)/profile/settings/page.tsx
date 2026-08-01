import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { SettingsShell } from '@/components/settings/settings-shell';
import { IconArrowLeft } from '@/components/ui/icons';
import { PageHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
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
      <div>
        <Link
          href="/profile"
          className="flex w-fit items-center gap-1.5 text-sm text-muted hover:text-text"
        >
          <IconArrowLeft className="size-4" />
          {t('backToProfile')}
        </Link>
        <div className="mt-4">
          <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
        </div>
      </div>

      <SettingsShell me={me} />
    </div>
  );
}
