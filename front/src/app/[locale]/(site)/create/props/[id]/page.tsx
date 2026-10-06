import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { PropManagePage } from '@/components/props/prop-manage-page';
import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { parseStyleSkillId } from '@/features/asset-workspace/style-skill';
import { parseWorkspaceTab } from '@/features/asset-workspace/tabs';
import { isSignedIn, serverFetchOrNull } from '@/lib/api/server';
import type { AssetGraph } from '@/lib/api/types';

interface Params {
  params: Promise<{ id: string }>;
  /** `look`: the condition to open on; `tab` / `slot`: `tabs.ts`. */
  searchParams: Promise<{ look?: string; tab?: string; slot?: string; skillId?: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations('props');
  return { title: t('manageEyebrow') };
}

/** One prop's workspace — conditions and their images. Owner-only: another
 * user's card is a 404 from `/v1/props/{id}/graph`. */
export default async function PropManageRoute({ params, searchParams }: Params) {
  const { id } = await params;
  const t = await getTranslations('props');
  const query = await searchParams;
  if (!(await isSignedIn())) return <SignInPrompt />;

  const prop = await serverFetchOrNull<AssetGraph>(`/v1/props/${encodeURIComponent(id)}/graph`, {
    authenticated: true,
  });
  if (!prop) notFound();

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      <BackLink href="/create/props">{t('backToLibrary')}</BackLink>
      <PageHeading eyebrow={t('manageEyebrow')} title={prop.name} />
      <PropManagePage
        initial={prop}
        initialVariantId={query.look}
        initialTab={parseWorkspaceTab(query.tab)}
        initialSlotId={query.slot}
        initialSkillId={parseStyleSkillId(query.skillId)}
      />
    </div>
  );
}
