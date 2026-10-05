import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { CharacterManagePage } from '@/components/characters/character-manage-page';
import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { isSignedIn, serverFetchOrNull } from '@/lib/api/server';
import type { Character } from '@/lib/api/types';

interface Params {
  params: Promise<{ id: string }>;
  /** `look`: the look to open on (the studio's 去定稿, a graph deep link). */
  searchParams: Promise<{ look?: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations('characters');
  return { title: t('manageEyebrow') };
}

/** One character's management page — looks and their images. Owner-only:
 * another user's card is a 404 from `/v1/characters/{id}`. */
export default async function CharacterManageRoute({ params, searchParams }: Params) {
  const { id } = await params;
  const t = await getTranslations('characters');
  if (!(await isSignedIn())) return <SignInPrompt />;

  const character = await serverFetchOrNull<Character>(`/v1/characters/${encodeURIComponent(id)}`, {
    authenticated: true,
  });
  if (!character) notFound();

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      <BackLink href="/create/characters">{t('backToLibrary')}</BackLink>
      <PageHeading eyebrow={t('manageEyebrow')} title={character.name} />
      <CharacterManagePage initial={character} initialLookId={(await searchParams).look} />
    </div>
  );
}
