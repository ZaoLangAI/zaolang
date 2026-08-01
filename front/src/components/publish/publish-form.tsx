'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { Poster } from '@/components/media/poster';
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

interface PublishResult {
  work_id: string;
  royalties_paid: Array<Record<string, unknown>>;
}

const VISIBILITIES: Visibility[] = ['public_remixable', 'public_view_only', 'private'];

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
  const [visibility, setVisibility] = useState<Visibility>('public_view_only');
  const [rights, setRights] = useState(false);
  const [disclosure, setDisclosure] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
          rights_confirmed: rights,
          ai_disclosure_confirmed: disclosure,
        },
        { idempotencyKey: newIdempotencyKey() },
      );
      router.push(`/work/${result.work_id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
      setPublishing(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex flex-col gap-4">
        <p className="text-sm font-medium">{t('coverLabel')}</p>
        <Poster
          src={draft.output_url}
          alt={title || t('title')}
          aspect="video"
          className="border border-border"
        />

        <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4 text-xs">
          <div className="flex items-center gap-2">
            <IconSparkle className="size-4 text-amber" />
            <span className="font-medium">{t('aiLabel')}</span>
          </div>

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

        <Button
          size="lg"
          loading={publishing}
          disabled={!title.trim() || !rights || !disclosure}
          onClick={() => void publish()}
        >
          {publishing ? t('publishing') : t('publishNow')}
        </Button>
      </aside>
    </div>
  );
}
