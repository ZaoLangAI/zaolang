'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { MarkdownBodyEditor } from '@/components/learn/markdown-body-editor';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { IconUpload } from '@/components/ui/icons';
import {
  Badge,
  type BadgeTone,
  EmptyState,
  ErrorNotice,
  SectionHeading,
} from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { useRouter } from '@/i18n/navigation';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type {
  LearnPostDetail,
  LearnPostLevel,
  LearnPostStatus,
  LearnPostSummary,
  Page,
} from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { uploadFile } from '@/lib/upload';

const LEVELS: LearnPostLevel[] = ['beginner', 'intermediate', 'advanced'];

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

const STATUS_TONE: Record<LearnPostStatus, BadgeTone> = {
  pending: 'amber',
  approved: 'success',
  rejected: 'danger',
  withdrawn: 'neutral',
};

/** 发表 / 编辑学习内容表单，外加下方的「我的发表」管理列表。 */
export function LearnPublishForm({ initialEditId }: { initialEditId: string | null }) {
  const t = useTranslations('learnPage');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');
  const { status: sessionStatus } = useSession();
  const { notify } = useToast();
  const router = useRouter();

  const [editingId, setEditingId] = useState<string | null>(initialEditId);
  const [editLoading, setEditLoading] = useState(Boolean(initialEditId));
  const editRequestRef = useRef<string | null>(null);

  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [level, setLevel] = useState<LearnPostLevel>('beginner');
  const [coverAssetId, setCoverAssetId] = useState<string | null>(null);
  const [coverPreviewUrl, setCoverPreviewUrl] = useState<string | null>(null);
  const [coverUploading, setCoverUploading] = useState(false);
  const [bodyMarkdown, setBodyMarkdown] = useState('');
  const [bodyAssetUrls, setBodyAssetUrls] = useState<Record<string, string>>({});

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [mine, setMine] = useState<LearnPostSummary[]>([]);
  const [mineLoading, setMineLoading] = useState(true);
  const [mineError, setMineError] = useState<string | null>(null);
  const [rejectReasons, setRejectReasons] = useState<Record<string, string>>({});
  const [withdrawTarget, setWithdrawTarget] = useState<string | null>(null);
  const [withdrawBusy, setWithdrawBusy] = useState(false);

  // MDXEditor 的 `markdown` 初始值只在挂载时生效——切换编辑目标或提交后回到
  // 新建态时，靠这个自增序号强制换掉 `key`，让编辑器整个重新挂载而不是
  // 带着上一篇内容的残留文档模型继续用。
  const [bodyEditorInstance, setBodyEditorInstance] = useState(0);

  const resetForm = useCallback(() => {
    setTitle('');
    setSummary('');
    setLevel('beginner');
    setCoverAssetId(null);
    setCoverPreviewUrl(null);
    setBodyMarkdown('');
    setBodyAssetUrls({});
    setBodyEditorInstance((current) => current + 1);
  }, []);

  const refreshMine = useCallback(async () => {
    setMineLoading(true);
    setMineError(null);
    try {
      const page = await api.get<Page<LearnPostSummary>>('/v1/learn/posts/mine', {
        query: { limit: 50 },
      });
      setMine(page.items);

      // `LearnPostSummary` 不带 `reject_reason`，只有详情接口有；作者本人
      // 能看自己每一条内容的详情，所以对被拒的条目补一次单独请求。
      const rejected = page.items.filter((item) => item.status === 'rejected');
      if (rejected.length > 0) {
        const details = await Promise.all(
          rejected.map((item) =>
            api.get<LearnPostDetail>(`/v1/learn/posts/${item.id}`).catch(() => null),
          ),
        );
        setRejectReasons((current) => {
          const next = { ...current };
          details.forEach((detail, index) => {
            const reason = detail?.reject_reason;
            if (reason) next[rejected[index]!.id] = reason;
          });
          return next;
        });
      }
    } catch {
      setMineError(tStates('errorHint'));
    } finally {
      setMineLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startEdit = useCallback(
    async (id: string) => {
      editRequestRef.current = id;
      setEditingId(id);
      setEditLoading(true);
      setFormError(null);
      router.replace(`/learn/publish?edit=${id}`);

      try {
        const detail = await api.get<LearnPostDetail>(`/v1/learn/posts/${id}`);
        if (editRequestRef.current !== id) return; // 用户已经切走，丢弃过期结果

        setTitle(detail.title);
        setSummary(detail.summary);
        setLevel(detail.level);
        setCoverAssetId(detail.cover_asset_id ?? null);
        setCoverPreviewUrl(detail.cover_url ?? null);
        setBodyMarkdown(detail.body_markdown);
        setBodyAssetUrls(detail.asset_urls ?? {});
        setBodyEditorInstance((current) => current + 1);
      } catch {
        if (editRequestRef.current === id) setFormError(tStates('errorHint'));
      } finally {
        if (editRequestRef.current === id) setEditLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [router],
  );

  const cancelEdit = useCallback(() => {
    editRequestRef.current = null;
    setEditingId(null);
    resetForm();
    setFormError(null);
    router.replace('/learn/publish');
  }, [resetForm, router]);

  // 只在挂载、以及登录态从 loading 变为 authenticated 时跑一次；`refreshMine`/
  // `startEdit` 引用的翻译函数每次渲染都可能换身份，故意不把它们放进依赖。
  useEffect(() => {
    if (sessionStatus !== 'authenticated') return;
    void (async () => {
      await refreshMine();
      if (initialEditId) await startEdit(initialEditId);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionStatus]);

  const handleCoverFile = async (file: File | undefined) => {
    if (!file) return;
    setCoverUploading(true);
    setFormError(null);
    try {
      const asset = await uploadFile(file, 'learn_media');
      setCoverAssetId(asset.id);
      setCoverPreviewUrl(asset.url ?? null);
    } catch (caught) {
      setFormError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
    } finally {
      setCoverUploading(false);
    }
  };

  const canSubmit =
    title.trim().length > 0 &&
    summary.trim().length > 0 &&
    !coverUploading &&
    !submitting &&
    !editLoading;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setFormError(null);
    try {
      const payload = {
        title: title.trim(),
        summary: summary.trim(),
        level,
        cover_asset_id: coverAssetId,
        body_markdown: bodyMarkdown,
      };

      if (editingId) {
        await api.patch<LearnPostDetail>(`/v1/learn/posts/${editingId}`, payload);
        notify(t('updateSuccess'), 'success');
      } else {
        await api.post<LearnPostDetail>('/v1/learn/posts', payload, {
          idempotencyKey: newIdempotencyKey(),
        });
        notify(t('submitSuccess'), 'success');
      }

      // 提交后留在发表页而不是跳详情页：新内容还在待审核，作者更可能想
      // 接着发下一篇，或者立刻在下面的「我的发表」里看到刚提交的状态。
      editRequestRef.current = null;
      setEditingId(null);
      resetForm();
      router.replace('/learn/publish');
      await refreshMine();
    } catch (caught) {
      setFormError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
    } finally {
      setSubmitting(false);
    }
  };

  const confirmWithdraw = async () => {
    if (!withdrawTarget) return;
    setWithdrawBusy(true);
    try {
      await api.post(`/v1/learn/posts/${withdrawTarget}/withdraw`);
      setWithdrawTarget(null);
      await refreshMine();
    } catch (caught) {
      notify(caught instanceof ApiError ? caught.message : tStates('errorHint'), 'error');
    } finally {
      setWithdrawBusy(false);
    }
  };

  if (sessionStatus === 'loading') {
    return (
      <div className="flex items-center gap-2 py-16 text-sm text-muted">
        <Spinner />
        {tStates('loading')}
      </div>
    );
  }

  // 与顶部创作下拉的登录墙同一套判断，双重兜底防止有人直接访问 URL 绕过
  // 服务端渲染时的登录检查（`publish/page.tsx` 已经做过一次）。
  if (sessionStatus === 'anonymous') {
    return <SignInPrompt description={t('signInRequired')} />;
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-5 rounded-[var(--radius-lg)] border border-border bg-surface p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">
            {editingId ? t('submitUpdate') : t('publishHeroTitle')}
          </h2>
          {editingId ? (
            <Button variant="ghost" size="sm" onClick={cancelEdit}>
              {t('cancelEdit')}
            </Button>
          ) : null}
        </div>

        {editLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Spinner />
            {tStates('loading')}
          </div>
        ) : (
          <>
            <div className="grid gap-5 sm:grid-cols-2">
              <div className="flex flex-col gap-4">
                <TextInput
                  label={t('formTitleLabel')}
                  placeholder={t('formTitlePlaceholder')}
                  required
                  value={title}
                  maxLength={80}
                  onChange={(event) => setTitle(event.target.value)}
                />
                <TextArea
                  label={t('formSummaryLabel')}
                  placeholder={t('formSummaryPlaceholder')}
                  required
                  value={summary}
                  maxLength={160}
                  className="min-h-20"
                  onChange={(event) => setSummary(event.target.value)}
                />
                <Select
                  label={t('formLevelLabel')}
                  value={level}
                  onChange={(event) => setLevel(event.target.value as LearnPostLevel)}
                  options={LEVELS.map((value) => ({ value, label: t(LEVEL_LABEL_KEY[value]) }))}
                />
              </div>

              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium text-text">{t('formCoverLabel')}</p>
                <p className="text-xs text-muted">{t('formCoverHint')}</p>
                <UploadTile
                  previewUrl={coverPreviewUrl}
                  label={t('formCoverLabel')}
                  busy={coverUploading}
                  onPick={(file) => void handleCoverFile(file)}
                  className="w-full"
                />
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium text-text">{t('formBodyLabel')}</p>
              <MarkdownBodyEditor
                key={bodyEditorInstance}
                markdown={bodyMarkdown}
                assetUrls={bodyAssetUrls}
                onChange={setBodyMarkdown}
              />
              <p className="text-xs text-muted">{t('bodyMarkdownHint')}</p>
            </div>

            {formError ? <ErrorNotice title={formError} /> : null}

            <div>
              <Button loading={submitting} disabled={!canSubmit} onClick={() => void submit()}>
                {editingId ? t('submitUpdate') : t('submitNew')}
              </Button>
            </div>
          </>
        )}
      </div>

      <div>
        <SectionHeading title={t('myPostsTitle')} />
        {mineError ? <ErrorNotice title={mineError} /> : null}
        {mineLoading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted">
            <Spinner />
            {tStates('loading')}
          </div>
        ) : mine.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {mine.map((post) => (
              <li
                key={post.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{post.title}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <Badge tone={STATUS_TONE[post.status]}>
                      {t(STATUS_LABEL_KEY[post.status])}
                    </Badge>
                    {post.status === 'rejected' && rejectReasons[post.id] ? (
                      <span className="text-xs text-muted">
                        {t('rejectReasonLabel', { reason: rejectReasons[post.id]! })}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button variant="secondary" size="sm" onClick={() => void startEdit(post.id)}>
                    {t('editAction')}
                  </Button>
                  {post.status !== 'withdrawn' ? (
                    <Button variant="ghost" size="sm" onClick={() => setWithdrawTarget(post.id)}>
                      {t('withdrawAction')}
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title={t('myPostsEmpty')} description={t('myPostsEmptyHint')} />
        )}
      </div>

      <Dialog
        open={withdrawTarget !== null}
        onClose={() => setWithdrawTarget(null)}
        title={t('withdrawAction')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setWithdrawTarget(null)}>
              {tActions('cancel')}
            </Button>
            <Button variant="danger" loading={withdrawBusy} onClick={() => void confirmWithdraw()}>
              {tActions('confirm')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t('withdrawConfirm')}</p>
      </Dialog>
    </div>
  );
}

/** 点击打开文件选择、有预览显示预览、上传中显示 spinner 的方块——封面和正文插图共用。 */
function UploadTile({
  previewUrl,
  label,
  busy,
  onPick,
  className,
}: {
  previewUrl: string | null;
  label: string;
  busy: boolean;
  onPick: (file: File | undefined) => void;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div
      className={cn('relative aspect-video overflow-hidden rounded-[var(--radius-sm)]', className)}
    >
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        aria-label={label}
        className={cn(
          'flex size-full flex-col items-center justify-center gap-1.5 border text-[11px] text-muted transition-colors focus-visible:outline-2',
          previewUrl
            ? 'border-border'
            : 'border-dashed border-border hover:border-border-strong hover:text-text',
          'disabled:cursor-not-allowed disabled:opacity-70',
        )}
      >
        {previewUrl ? (
          <Image src={previewUrl} alt="" fill sizes="220px" className="object-cover" />
        ) : busy ? (
          <Spinner className="size-4" />
        ) : (
          <>
            <IconUpload className="size-4" />
            {label}
          </>
        )}
      </button>
      {previewUrl && busy ? (
        <div className="absolute inset-0 grid place-items-center bg-surface/70">
          <Spinner className="size-4" />
        </div>
      ) : null}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="sr-only"
        onChange={(event) => {
          onPick(event.target.files?.[0]);
          event.target.value = '';
        }}
      />
    </div>
  );
}
