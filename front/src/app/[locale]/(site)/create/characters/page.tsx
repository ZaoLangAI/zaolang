import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { CharacterLibrary } from '@/components/characters/character-library';
import { CarriedStyleSkill } from '@/features/asset-workspace/carried-style-skill';
import { parseStyleSkillId, withStyleSkill } from '@/features/asset-workspace/style-skill';
import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { redirect } from '@/i18n/navigation';
import { isSignedIn, serverFetchOrNull } from '@/lib/api/server';
import type { Character } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('characters');
  return { title: t('title'), description: t('subtitle') };
}

/**
 * A creator's cast: reusable faces and voice hints so a multi-episode short
 * stays consistent without retyping a description on every draft.
 */
export default async function CharactersPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  /** `manage`: a pre-page link (the old looks drawer) — now the card's own page. */
  searchParams: Promise<{ manage?: string; skillId?: string }>;
}) {
  const t = await getTranslations('characters');
  const tActions = await getTranslations('actions');
  const { manage, skillId } = await searchParams;
  // A plaza 用于…创作 click: a style skill for this card's 创作 slots.
  const styleSkillId = parseStyleSkillId(skillId);
  if (manage) {
    redirect({
      href: withStyleSkill(`/create/characters/${encodeURIComponent(manage)}`, styleSkillId),
      locale: (await params).locale,
    });
  }
  if (!(await isSignedIn())) return <SignInPrompt />;

  const characters = await serverFetchOrNull<Character[]>('/v1/characters', {
    authenticated: true,
  });
  if (!characters) return <SignInPrompt />;

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <GoBackLink fallbackHref="/create">{tActions('back')}</GoBackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
      {styleSkillId ? <CarriedStyleSkill skillId={styleSkillId} /> : null}
      <CharacterLibrary initial={characters} styleSkillId={styleSkillId} />
    </div>
  );
}
