import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { SceneLibrary } from '@/components/scenes/scene-library';
import { CarriedStyleSkill } from '@/features/asset-workspace/carried-style-skill';
import { parseStyleSkillId, withStyleSkill } from '@/features/asset-workspace/style-skill';
import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { redirect } from '@/i18n/navigation';
import { isSignedIn, serverFetchOrNull } from '@/lib/api/server';
import type { Scene } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('scenes');
  return { title: t('title'), description: t('subtitle') };
}

/**
 * A creator's reusable settings: locations whose look (and, once generated,
 * whose reference stills) should stay consistent across a multi-episode
 * short without retyping a description on every scene heading.
 */
export default async function ScenesPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  /** `manage`: a pre-page link (the old looks drawer) — now the card's own page. */
  searchParams: Promise<{ manage?: string; skillId?: string }>;
}) {
  const t = await getTranslations('scenes');
  const tActions = await getTranslations('actions');
  const { manage, skillId } = await searchParams;
  // A plaza 用于…创作 click: a style skill for this card's 创作 slots.
  const styleSkillId = parseStyleSkillId(skillId);
  if (manage) {
    redirect({
      href: withStyleSkill(`/create/scenes/${encodeURIComponent(manage)}`, styleSkillId),
      locale: (await params).locale,
    });
  }
  if (!(await isSignedIn())) return <SignInPrompt />;

  const scenes = await serverFetchOrNull<Scene[]>('/v1/scenes', {
    authenticated: true,
  });
  if (!scenes) return <SignInPrompt />;

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <GoBackLink fallbackHref="/create">{tActions('back')}</GoBackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
      {styleSkillId ? <CarriedStyleSkill skillId={styleSkillId} /> : null}
      <SceneLibrary initial={scenes} styleSkillId={styleSkillId} />
    </div>
  );
}
