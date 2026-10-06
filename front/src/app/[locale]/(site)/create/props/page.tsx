import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { PropLibrary } from '@/components/props/prop-library';
import { GoBackLink } from '@/components/ui/go-back-link';
import { PageHeading } from '@/components/ui/primitives';
import { redirect } from '@/i18n/navigation';
import { isSignedIn, serverFetchOrNull } from '@/lib/api/server';
import type { Prop } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('props');
  return { title: t('title'), description: t('subtitle') };
}

/**
 * 道具创作: a creator's reusable objects — a token, a weapon, a letter —
 * whose look should hold across shots and episodes. Each card opens its
 * own workspace.
 */
export default async function PropsPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  /** `manage`: a card link in the list-page shape — now the card's own page. */
  searchParams: Promise<{ manage?: string }>;
}) {
  const t = await getTranslations('props');
  const tActions = await getTranslations('actions');
  const { manage } = await searchParams;
  if (manage) {
    redirect({
      href: `/create/props/${encodeURIComponent(manage)}`,
      locale: (await params).locale,
    });
  }
  if (!(await isSignedIn())) return <SignInPrompt />;

  const props = await serverFetchOrNull<Prop[]>('/v1/props', { authenticated: true });
  if (!props) return <SignInPrompt />;

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-6 sm:px-6">
      <GoBackLink fallbackHref="/create">{tActions('back')}</GoBackLink>
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />
      <PropLibrary initial={props} />
    </div>
  );
}
