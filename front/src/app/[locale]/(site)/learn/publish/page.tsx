import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { LearnPublishForm } from '@/components/learn/learn-publish-form';
import { PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Me } from '@/lib/api/types';

interface Params {
  searchParams: Promise<{ edit?: string }>;
}

export async function generateMetadata() {
  const t = await getTranslations('learnPage');
  return { title: t('publishHeroTitle'), description: t('publishHeroSubtitle') };
}

export default async function LearnPublishPage({ searchParams }: Params) {
  const t = await getTranslations('learnPage');
  const { edit } = await searchParams;

  // 与 `billing`/`profile/settings` 同一套模式：服务端先用刷新 cookie 探测
  // 登录态，未登录直接渲染登录提示，免得客户端组件先闪一下空表单。
  const me = await serverFetchOrNull<Me>('/v1/auth/me', { authenticated: true });
  if (!me) return <SignInPrompt description={t('signInRequired')} />;

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6">
      <PageHeading
        eyebrow={t('eyebrow')}
        title={t('publishHeroTitle')}
        description={t('publishHeroSubtitle')}
      />
      <LearnPublishForm initialEditId={edit ?? null} />
    </div>
  );
}
