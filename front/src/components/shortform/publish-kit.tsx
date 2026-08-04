'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { DevicePreview } from '@/components/media/device-preview';
import { CaptionComposer, type Caption } from '@/components/shortform/caption-composer';
import {
  CompliancePanel,
  blockingChecks,
  useSafeAreaCheck,
} from '@/components/shortform/compliance-panel';
import { Button } from '@/components/ui/button';
import { IconCopy, IconUpload, IconVideo } from '@/components/ui/icons';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type {
  ComplianceCheck,
  ComplianceReport,
  Draft,
  PublicationIntent,
  ShortformProfile,
} from '@/lib/api/types';
import { DEFAULT_DEVICE_ID } from '@/lib/devices';
import { formatDateTime } from '@/lib/format';
import { captionText, chromeOf } from '@/lib/shortform';

const CHANNEL_LABEL_KEYS: Record<string, string> = {
  manual_download: 'kitChannelManual',
  douyin: 'kitChannelDouyin',
};

const STATUS_LABEL_KEYS: Record<string, string> = {
  draft: 'kitStatusDraft',
  ready: 'kitStatusReady',
  exported: 'kitStatusExported',
  submitted: 'kitStatusSubmitted',
  failed: 'kitStatusFailed',
};

/**
 * What a creator takes to the destination app.
 *
 * Distribution stops here on purpose: the platform hands back the file and the
 * caption, and the post is made by hand. The export is still recorded through
 * `POST /v1/works/{id}/publications`, so the day a direct-publish integration
 * exists it advances rows that already have a history instead of inventing one.
 */
export function PublishKit({
  draft,
  profile,
  initialIntents,
  initialCaption,
}: {
  draft: Draft;
  profile: ShortformProfile;
  initialIntents: PublicationIntent[];
  initialCaption: Caption;
}) {
  const t = useTranslations('shortform');
  const tStates = useTranslations('states');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const workId = draft.published_work_id ?? null;

  const [caption, setCaption] = useState<Caption>(initialCaption);
  const [serverChecks, setServerChecks] = useState<ComplianceCheck[]>([]);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [intents, setIntents] = useState<PublicationIntent[]>(initialIntents);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(
    initialIntents.find((intent) => intent.download_url)?.download_url ?? draft.output_url ?? null,
  );
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState({ rights: false, disclosure: false, manual: false });

  const safeArea = useSafeAreaCheck(caption.title, profile);
  const checks = [...serverChecks, safeArea];
  const blocking = blockingChecks(checks);

  // The check reads the caption through a ref so re-running it never widens the
  // dependencies of the effect that fires it once on arrival.
  const captionRef = useRef(caption);
  useEffect(() => {
    captionRef.current = caption;
  }, [caption]);

  const runCheck = useCallback(async () => {
    setChecking(true);
    setCheckError(null);
    try {
      const report = await api.post<ComplianceReport>('/v1/shortform/compliance-check', {
        draft_id: draft.id,
        profile: profile.key,
        title: captionRef.current.title.trim(),
        description: captionRef.current.description.trim(),
        hashtags: captionRef.current.hashtags,
      });
      setServerChecks(report.checks);
    } catch (caught) {
      setCheckError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
    } finally {
      setChecking(false);
    }
  }, [draft.id, profile.key, tStates]);

  // Once on arrival, then only when asked. The check persists a moderation
  // verdict and spends the write budget, so it is not wired to every keystroke
  // and the guard makes sure a re-created callback cannot fire it twice.
  const checkedOnce = useRef(false);
  useEffect(() => {
    if (checkedOnce.current) return;
    checkedOnce.current = true;
    void runCheck();
  }, [runCheck]);

  const copy = async (text: string) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      notify(t('kitCopied'), 'success');
    } catch {
      notify(tStates('errorHint'), 'error');
    }
  };

  const exportKit = async () => {
    if (!workId) return;
    setExporting(true);
    setExportError(null);
    setFieldErrors({});
    try {
      const intent = await api.post<PublicationIntent>(
        `/v1/works/${workId}/publications`,
        {
          channel: 'manual_download',
          title: caption.title.trim(),
          description: caption.description.trim() || null,
          hashtags: caption.hashtags,
        },
        // One export is one intent; a retried click must not record two.
        { idempotencyKey: newIdempotencyKey() },
      );
      setIntents((current) => [intent, ...current]);
      if (intent.download_url) setDownloadUrl(intent.download_url);
      notify(t('kitExported'), 'success');
    } catch (caught) {
      setExportError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
      if (caught instanceof ApiError) setFieldErrors(caught.fieldErrors);
    } finally {
      setExporting(false);
    }
  };

  const allConfirmed = confirmed.rights && confirmed.disclosure && confirmed.manual;
  const canExport =
    workId !== null &&
    caption.title.trim().length > 0 &&
    blocking.length === 0 &&
    allConfirmed &&
    !exporting;

  return (
    <div className="flex min-w-0 flex-col gap-6 lg:grid lg:grid-cols-[340px_minmax(0,1fr)] lg:items-start">
      <div className="flex min-w-0 flex-col gap-3">
        <DevicePreview
          src={draft.output_url}
          title={caption.title || t('kitTitle')}
          defaultDeviceId={DEFAULT_DEVICE_ID}
          maxHeight={520}
          chrome={chromeOf(profile)}
        />
        <p className="text-xs leading-relaxed text-muted">{t('kitPreviewHint')}</p>
      </div>

      <div className="flex min-w-0 flex-col gap-5">
        {workId === null ? (
          <ErrorNotice
            title={t('kitPublishFirst')}
            detail={t('kitPublishFirstHint')}
            action={
              <Link
                href={`/publish/${draft.id}`}
                className="text-xs font-medium text-primary hover:underline"
              >
                {t('kitGoPublish')}
              </Link>
            }
          />
        ) : null}

        <section className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold">{t('captionTitle')}</h2>
          <p className="mt-1 text-xs text-muted">{t('kitCaptionHint')}</p>
          <CaptionComposer
            profile={profile}
            value={caption}
            onChange={setCaption}
            fieldErrors={fieldErrors}
            className="mt-4"
          />

          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={<IconCopy className="size-4" />}
              disabled={caption.title.trim().length === 0}
              onClick={() => void copy(caption.title.trim())}
            >
              {t('kitCopyTitle')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<IconCopy className="size-4" />}
              disabled={caption.hashtags.length === 0}
              onClick={() => void copy(caption.hashtags.map((tag) => `#${tag}`).join(' '))}
            >
              {t('kitCopyHashtags')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<IconCopy className="size-4" />}
              onClick={() =>
                void copy(captionText(caption.title, caption.description, caption.hashtags))
              }
            >
              {t('kitCopyAll')}
            </Button>
          </div>
        </section>

        <CompliancePanel
          items={checks}
          title={t('complianceTitle')}
          hint={t('complianceServerHint')}
          loading={checking}
          error={checkError}
          onRecheck={() => void runCheck()}
          recheckLabel={t('complianceRecheck')}
        />

        <section className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold">{t('kitChecklist')}</h2>
          <Confirm
            label={t('kitConfirmRights')}
            checked={confirmed.rights}
            onChange={(next) => setConfirmed((current) => ({ ...current, rights: next }))}
          />
          <Confirm
            label={t('kitConfirmDisclosure')}
            checked={confirmed.disclosure}
            onChange={(next) => setConfirmed((current) => ({ ...current, disclosure: next }))}
          />
          <Confirm
            label={t('kitConfirmManual')}
            checked={confirmed.manual}
            onChange={(next) => setConfirmed((current) => ({ ...current, manual: next }))}
          />

          {blocking.length > 0 ? <p className="text-xs text-danger">{t('kitBlocked')}</p> : null}
          {exportError ? <ErrorNotice title={exportError} /> : null}

          <div className="flex flex-wrap gap-3">
            <Button
              icon={<IconUpload className="size-4" />}
              disabled={!canExport}
              loading={exporting}
              onClick={() => void exportKit()}
            >
              {exporting ? t('kitExporting') : t('kitExport')}
            </Button>
            {downloadUrl ? (
              // A real link, not a fetch: the signed URL is what the phone or
              // the editing app needs, and a download attribute keeps the file
              // out of a new tab.
              <a
                href={downloadUrl}
                download
                className="inline-flex h-11 items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-4 text-sm font-medium transition-colors hover:bg-surface-raised"
              >
                <IconVideo className="size-4" aria-hidden="true" />
                {t('kitDownload')}
              </a>
            ) : (
              <p className="self-center text-xs text-muted">{t('kitNoOutput')}</p>
            )}
            {workId ? (
              <Link
                href={`/work/${workId}`}
                className="inline-flex h-11 items-center px-2 text-sm text-muted hover:text-text"
              >
                {t('kitOpenWork')}
              </Link>
            ) : null}
          </div>
        </section>

        <section className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold">{t('kitHistory')}</h2>
          {intents.length === 0 ? (
            <p className="mt-3 text-xs text-muted">{t('kitHistoryEmpty')}</p>
          ) : (
            <ul className="mt-3 flex flex-col gap-3">
              {intents.map((intent) => (
                <li key={intent.id} className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone={intent.status === 'failed' ? 'danger' : 'success'}>
                    {t(STATUS_LABEL_KEYS[intent.status] ?? 'kitStatusDraft')}
                  </Badge>
                  <span className="text-muted">
                    {t(CHANNEL_LABEL_KEYS[intent.channel] ?? 'kitChannelManual')}
                  </span>
                  <span className="tabular ml-auto text-muted">
                    {formatDateTime(intent.created_at, locale)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function Confirm({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
      />
      {label}
    </label>
  );
}
