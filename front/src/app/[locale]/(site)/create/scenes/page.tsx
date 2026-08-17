import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { SceneLibrary } from '@/components/scenes/scene-library';
import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import { isSignedIn, serverFetchOrNull } from '@/lib/api/server';
import type { Scene } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('scenes');
  return { title: t('title'), description: t('subtitle') };
}

/**
 * A creator's reusable settings: locations whose look (and, once generated,
 * whose reference stills or clips) should stay consistent across a
 * multi-episode short without retyping a description on every scene heading.
 */
export default async function ScenesPage() {
  const t = await getTranslations('scenes');
  if (!(await isSignedIn())) return <SignInPrompt />;

  const scenes = await serverFetchOrNull<Scene[]>('/v1/scenes', {
    authenticated: true,
  });
  if (!scenes) return <SignInPrompt />;

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <BackLink href="/create">{t('backToCreate')}</BackLink>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
        <Link href="/create/characters" className="text-sm text-muted hover:text-text">
          {t('characterLibraryLink')}
        </Link>
      </div>
      <SceneLibrary initial={scenes} />
    </div>
  );
}
