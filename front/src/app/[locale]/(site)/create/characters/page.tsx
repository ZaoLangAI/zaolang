import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { CharacterLibrary } from '@/components/characters/character-library';
import { PageHeading } from '@/components/ui/primitives';
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
export default async function CharactersPage() {
  const t = await getTranslations('characters');
  if (!(await isSignedIn())) return <SignInPrompt />;

  const characters = await serverFetchOrNull<Character[]>('/v1/characters', {
    authenticated: true,
  });
  if (!characters) return <SignInPrompt />;

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
      <CharacterLibrary initial={characters} />
    </div>
  );
}
