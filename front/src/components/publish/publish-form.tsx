'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { DevicePreview } from '@/components/media/device-preview';
import { Button } from '@/components/ui/button';
import { TextArea, TextInput } from '@/components/ui/field';
import { IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { OptionGroup } from '@/components/studio/option-group';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Draft, Visibility } from '@/lib/api/types';
import { formatDate } from '@/lib/format';
import { refreshDraftOutputUrl } from '@/lib/refresh-media-src';

interface PublishResult {
  work_id: string;
  royalties_paid: Array<Record<string, unknown>>;
}

const VISIBILITIES: Visibility[] = ['public_remixable', 'public_view_only', 'private'];

const OPERATIONS = [
  'text_to_image',
  'image_to_image',
  'text_to_video',
  'image_to_video',
  'video_to_video',
  'audio_generation',
] as const;

const TIERS = ['preview', 'standard', 'cinematic'] as const;

type OperationKey = (typeof OPERATIONS)[number];
type TierKey = (typeof TIERS)[number];

/** Drafts created by the short-form studio carry the spec they were made for. */
function isShortform(draft: Draft): boolean {
  return typeof draft.params?.shortform_profile === 'string';
}

function stringParam(params: Draft['params'], key: string): string | null {
  const value = params?.[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

function numberParam(params: Draft['params'], key: string): number | null {
  const value = params?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function isOperation(value: string): value is OperationKey {
  return (OPERATIONS as readonly string[]).includes(value);
}

function isTier(value: string): value is TierKey {
  return (TIERS as readonly string[]).includes(value);
}

/**
 * The last step before a work becomes public.
 *
 * Both confirmations are unchecked by default and the backend refuses the
 * request without them: consenting to publish is not the same as asserting you
 * hold the rights, and neither can be assumed from the other.
 */
export function PublishForm({ draft }: { draft: Draft }) {
  const t = useTranslations('publishPage');
  const tVisibility = useTranslations('visibility');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const router = useRouter();

  const [title, setTitle] = useState(draft.title ?? '');
  const [description, setDescription] = useState(draft.description ?? '');
  const [visibility, setVisibility] = useState<Visibility>('public_remixable');
  const [accessCredits, setAccessCredits] = useState(0);
  const [rights, setRights] = useState(false);
  const [disclosure, setDisclosure] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const previewTitle = title || t('title');
  const isPlayable = draft.output_media_type === 'video' || draft.output_media_type === 'audio';
  const specRows = draftSpecRows(draft, t, locale);

  const publish = async () => {
    setPublishing(true);
    setError(null);
    try {
      const result = await api.post<PublishResult>(
        `/v1/drafts/${draft.id}/publish`,
        {
          title: title.trim(),
          description: description.trim() || null,
          visibility,
          access_credits: visibility === 'public_remixable' ? accessCredits : 0,
          rights_confirmed: rights,
          ai_disclosure_confirmed: disclosure,
        },
        { idempotencyKey: newIdempotencyKey() },
      );
      // A vertical draft has one step left: the export kit, which is where its
      // caption and the compliance checklist live. Everything else is done once
      // the work exists.
      router.push(
        isShortform(draft) ? `/create/short?draftId=${draft.id}` : `/work/${result.work_id}`,
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
      setPublishing(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex flex-col gap-4">
        <p className="text-sm font-medium">{isPlayable ? t('previewLabel') : t('coverLabel')}</p>
        <DraftOutput draft={draft} title={previewTitle} />

        <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4 text-xs">
          <div className="flex items-center gap-2">
            <IconSparkle className="size-4 text-amber" />
            <span className="font-medium">{t('aiLabel')}</span>
          </div>

          {specRows.prompt ? (
            <div>
              <p className="font-medium">{t('prompt')}</p>
              <p className="mt-1 whitespace-pre-wrap text-muted">{specRows.prompt}</p>
            </div>
          ) : null}

          {specRows.rows.length > 0 ? (
            <dl className="flex flex-col gap-2">
              {specRows.rows.map((row) => (
                <div key={row.key} className="flex justify-between gap-3">
                  <dt className="shrink-0 text-muted">{row.label}</dt>
                  <dd className="min-w-0 text-right">{row.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}

          {draft.source_work_version_id ? (
            <p className="text-muted">
              {t('parentVersion')} · {draft.source_work_version_id}
            </p>
          ) : null}

          {draft.license ? (
            <p className="flex flex-wrap items-center gap-2 text-muted">
              <Badge tone="amber">{draft.license.license_type}</Badge>
              {draft.license.attribution_text}
              {draft.license.captured_at ? (
                <span>· {formatDate(draft.license.captured_at, locale)}</span>
              ) : null}
            </p>
          ) : null}
        </div>
      </div>

      <aside className="flex flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
        <TextInput
          label={t('titleField')}
          required
          value={title}
          maxLength={200}
          onChange={(event) => setTitle(event.target.value)}
        />

        <TextArea
          label={t('descriptionField')}
          value={description}
          maxLength={2000}
          onChange={(event) => setDescription(event.target.value)}
        />

        <OptionGroup
          label={t('visibilityField')}
          value={visibility}
          onChange={setVisibility}
          options={VISIBILITIES.map((value) => ({ value, label: tVisibility(value) }))}
        />

        {visibility === 'public_remixable' ? (
          <AccessPriceField
            value={accessCredits}
            onChange={setAccessCredits}
            label={t('accessCredits')}
            hint={t('accessCreditsHint')}
          />
        ) : null}

        <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
          <input
            type="checkbox"
            checked={rights}
            onChange={(event) => setRights(event.target.checked)}
            className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
          />
          {t('rightsConfirm')}
        </label>

        <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
          <input
            type="checkbox"
            checked={disclosure}
            onChange={(event) => setDisclosure(event.target.checked)}
            className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
          />
          {t('aiLabel')}
        </label>

        {error ? <ErrorNotice title={error} /> : null}

        {/* Keeps the last checkbox clear of the fixed bar below. */}
        <div aria-hidden="true" className="safe-mb h-16 lg:hidden" />

        <div className="safe-b fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface px-4 py-3 lg:static lg:border-0 lg:bg-transparent lg:px-0 lg:py-0">
          <Button
            size="lg"
            fullWidth
            loading={publishing}
            disabled={!title.trim() || !rights || !disclosure}
            onClick={() => void publish()}
          >
            {publishing ? t('publishing') : t('publishNow')}
          </Button>
        </div>
      </aside>
    </div>
  );
}

function DraftOutput({ draft, title }: { draft: Draft; title: string }) {
  if (draft.output_media_type === 'audio' && draft.output_url) {
    return (
      <audio
        src={draft.output_url}
        controls
        className="w-full rounded-[var(--radius-md)] border border-border p-4"
      />
    );
  }
  return (
    <DevicePreview
      src={draft.output_url}
      title={title}
      mediaType={draft.output_media_type === 'image' ? 'image' : 'video'}
      refreshSrc={() => refreshDraftOutputUrl(draft.id)}
    />
  );
}

function draftSpecRows(
  draft: Draft,
  t: ReturnType<typeof useTranslations<'publishPage'>>,
  locale: Locale,
): { prompt: string | null; rows: Array<{ key: string; label: string; value: string }> } {
  const prompt = stringParam(draft.params, 'prompt');
  const operation = stringParam(draft.params, 'operation');
  const quality = stringParam(draft.params, 'quality_tier');
  const aspect = stringParam(draft.params, 'aspect_ratio');
  const durationSeconds =
    draft.duration_ms != null && draft.duration_ms > 0
      ? draft.duration_ms / 1000
      : numberParam(draft.params, 'duration_seconds');
  const rows: Array<{ key: string; label: string; value: string }> = [];

  if (operation) {
    rows.push({
      key: 'operation',
      label: t('operationLabel'),
      value: isOperation(operation) ? t(`operation.${operation}`) : operation,
    });
  }
  if (quality) {
    rows.push({
      key: 'quality',
      label: t('quality'),
      value: isTier(quality) ? t(`tier.${quality}`) : quality,
    });
  }
  if (aspect) {
    rows.push({ key: 'aspect', label: t('aspect'), value: aspect });
  }
  if (durationSeconds != null && durationSeconds > 0) {
    rows.push({
      key: 'duration',
      label: t('duration'),
      value: t('durationSeconds', { count: Math.round(durationSeconds) }),
    });
  }
  if (draft.width && draft.height) {
    rows.push({
      key: 'resolution',
      label: t('resolution'),
      value: `${draft.width}×${draft.height}`,
    });
  }
  rows.push({
    key: 'createdAt',
    label: t('createdAt'),
    value: formatDate(draft.created_at, locale),
  });

  return { prompt, rows };
}
