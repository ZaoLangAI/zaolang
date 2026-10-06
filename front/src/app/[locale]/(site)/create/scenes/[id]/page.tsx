import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { SceneManagePage } from '@/components/scenes/scene-manage-page';
import { BackLink } from '@/components/ui/back-link';
import { PageHeading } from '@/components/ui/primitives';
import { parseStyleSkillId } from '@/features/asset-workspace/style-skill';
import { parseWorkspaceTab } from '@/features/asset-workspace/tabs';
import { isSignedIn, serverFetchOrNull } from '@/lib/api/server';
import type { AssetGraph } from '@/lib/api/types';

interface Params {
  params: Promise<{ id: string }>;
  /** `look`: the variant to open on (the studio's 去定稿, a graph deep link). */
  searchParams: Promise<{ look?: string; tab?: string; slot?: string; skillId?: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations('scenes');
  return { title: t('manageEyebrow') };
}

/** One scene's management page — variants and their images. Owner-only:
 * another user's card is a 404 from `/v1/scenes/{id}`. */
export default async function SceneManageRoute({ params, searchParams }: Params) {
  const { id } = await params;
  const t = await getTranslations('scenes');
  const query = await searchParams;
  if (!(await isSignedIn())) return <SignInPrompt />;

  const scene = await serverFetchOrNull<AssetGraph>(`/v1/scenes/${encodeURIComponent(id)}/graph`, {
    authenticated: true,
  });
  if (!scene) notFound();

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      <BackLink href="/create/scenes">{t('backToLibrary')}</BackLink>
      <PageHeading eyebrow={t('manageEyebrow')} title={scene.name} />
      <SceneManagePage
        initial={scene}
        initialVariantId={query.look}
        initialTab={parseWorkspaceTab(query.tab)}
        initialSlotId={query.slot}
        initialSkillId={parseStyleSkillId(query.skillId)}
      />
    </div>
  );
}
