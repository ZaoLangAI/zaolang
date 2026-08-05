import { cache } from 'react';

import { notFound } from 'next/navigation';
import { getLocale, getTranslations } from 'next-intl/server';

import { LearnBodyView } from '@/components/learn/learn-body-view';
import { Poster } from '@/components/media/poster';
import { Avatar } from '@/components/work/avatar';
import { Badge } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { serverFetchOrNull } from '@/lib/api/server';
import type { LearnPostDetail, LearnPostLevel, LearnPostStatus } from '@/lib/api/types';
import { formatDate } from '@/lib/format';

const LEVEL_LABEL_KEY: Record<LearnPostLevel, string> = {
  beginner: 'levelBeginner',
  intermediate: 'levelIntermediate',
  advanced: 'levelAdvanced',
};

const STATUS_LABEL_KEY: Record<LearnPostStatus, string> = {
  pending: 'statusPending',
  approved: 'statusApproved',
  rejected: 'statusRejected',
  withdrawn: 'statusWithdrawn',
};

interface Params {
  params: Promise<{ postId: string }>;
}

/**
 * `authenticated: true` 是为了让作者本人能看到自己未过审的内容——
 * `GET /v1/learn/posts/{id}` 对其它状态只放行作者本人，其余人一律 404。
 * `cache()` 让 `generateMetadata` 与页面正文共享同一次请求。
 */
const getLearnPost = cache(async (postId: string) => {
  return serverFetchOrNull<LearnPostDetail>(`/v1/learn/posts/${postId}`, { authenticated: true });
});

export async function generateMetadata({ params }: Params) {
  const { postId } = await params;
  const post = await getLearnPost(postId);
  if (!post) {
    const tStates = await getTranslations('states');
    return { title: tStates('notFound') };
  }
  return {
    title: `${post.title} · ${post.author.display_name}`,
    description: post.summary,
  };
}

export default async function LearnPostPage({ params }: Params) {
  const { postId } = await params;
  const t = await getTranslations('learnPage');
  const tStates = await getTranslations('states');
  const locale = (await getLocale()) as Locale;

  const post = await getLearnPost(postId);
  // 未通过审核的内容对非作者一律表现为「不存在」，这里统一走 notFound()，
  // 不额外拼一个「无权限」提示，避免暴露内容存在与否。
  if (!post) notFound();

  return (
    <div className="mx-auto flex w-full max-w-[860px] flex-col gap-6 px-4 py-8 sm:px-6">
      <Link href="/learn" className="w-fit text-sm text-muted hover:text-text">
        {t('listTitle')}
      </Link>

      <Poster src={post.cover_url} alt={post.title} aspect="video" priority />

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="amber">{t(LEVEL_LABEL_KEY[post.level])}</Badge>
        {post.status !== 'approved' ? (
          <Badge tone={post.status === 'rejected' ? 'danger' : 'neutral'}>
            {t(STATUS_LABEL_KEY[post.status])}
          </Badge>
        ) : null}
      </div>

      <div>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{post.title}</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">{post.summary}</p>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-b border-border pb-5 text-sm text-muted">
        <Avatar src={post.author.avatar_url} name={post.author.display_name} size="sm" />
        <span className="text-text">{post.author.display_name}</span>
        <span aria-hidden="true">·</span>
        <span>{formatDate(post.published_at ?? post.created_at, locale)}</span>
      </div>

      {post.status === 'rejected' && post.reject_reason ? (
        <p className="rounded-[var(--radius-sm)] border border-danger/40 bg-danger/8 px-4 py-3 text-sm text-danger">
          {t('rejectReasonLabel', { reason: post.reject_reason })}
        </p>
      ) : null}

      <LearnBodyView
        markdown={post.body_markdown}
        assetUrls={post.asset_urls ?? {}}
        emptyImageLabel={tStates('empty')}
      />
    </div>
  );
}
