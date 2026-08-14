'use client';

import { useTranslations } from 'next-intl';
import { useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import { useRouter } from '@/i18n/navigation';
import { isApiError } from '@/lib/api/errors';
import type { ShortformProfile } from '@/lib/api/types';
import { sha256Hex } from '@/lib/upload';

import * as editorApi from './api';
import { browserInstanceId } from './browser';
import { SequentialExportRunner } from './engine/export-runner';
import { TICKS_PER_SECOND, type CanonicalDocument, type ResolvedAsset } from './engine/ports';

export function ExportPanel({
  revisionId,
  document,
  assets,
  durationTicks,
  draftId,
  disabled,
  profiles,
}: {
  revisionId: string | null;
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  durationTicks: number;
  draftId: string | null;
  disabled: boolean;
  profiles: ShortformProfile[];
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const router = useRouter();
  const [picked, setPicked] = useState<Set<string>>(
    new Set(profiles.slice(0, 1).map((item) => item.key)),
  );
  const [busy, setBusy] = useState(false);
  const [lastExportId, setLastExportId] = useState<string | null>(null);
  const runner = useMemo(() => new SequentialExportRunner(), []);
  const controllerRef = useRef<AbortController | null>(null);
  const claimedExportIdRef = useRef<string | null>(null);

  const run = async () => {
    if (!revisionId || picked.size === 0) return;
    setBusy(true);
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const variants = await editorApi.batchCreateVariants(revisionId, [...picked]);
      await editorApi.queueExports(variants.map((item) => item.id));
      const claimed = await editorApi.claimExport(browserInstanceId());
      claimedExportIdRef.current = claimed.id;
      const spec = {
        profile_key: claimed.variant_id,
        width: variants[0]?.width ?? 1080,
        height: variants[0]?.height ?? 1920,
        fps_num: 30,
        fps_den: 1,
        format: 'mp4' as const,
        caption_language: null,
        caption_mode: 'burned' as const,
        max_duration_ticks: Math.min(durationTicks, 30 * TICKS_PER_SECOND),
      };
      let blob: Blob | undefined;
      for await (const progress of runner.export(spec, document, assets, controller.signal)) {
        await editorApi.heartbeatExport(claimed.id, progress.percent, progress.stage);
        blob = progress.blob ?? blob;
      }
      if (!blob) throw new Error('empty_export');
      const checksum = await sha256Hex(await blob.arrayBuffer());
      const presigned = await editorApi.presignExportUpload(claimed.id, {
        filename: 'cut.mp4',
        mime_type: 'video/mp4',
        size_bytes: blob.size,
        checksum_sha256: checksum,
      });
      const put = await fetch(presigned.upload_url, {
        method: 'PUT',
        headers: presigned.required_headers,
        body: blob,
      });
      if (!put.ok) throw new Error(`upload ${put.status}`);
      const done = await editorApi.completeExport(claimed.id, presigned.upload_session_id);
      setLastExportId(done.id);
      notify(t('exportDone'), 'success');
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        notify(t('exportCancelled'), 'info');
      } else {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      }
    } finally {
      setBusy(false);
      controllerRef.current = null;
      claimedExportIdRef.current = null;
    }
  };

  const cancel = () => {
    controllerRef.current?.abort();
    const exportId = claimedExportIdRef.current;
    if (exportId) void editorApi.cancelExport(exportId).catch(() => undefined);
  };

  const bind = async () => {
    if (!draftId || !lastExportId) return;
    setBusy(true);
    try {
      await editorApi.bindEditorExport(draftId, lastExportId);
      router.push(`/publish/${draftId}`);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold">{t('exportTitle')}</h2>
      <p className="text-xs text-muted">{t('exportHint')}</p>
      <p className="text-xs text-muted">{t('hardLimitHint')}</p>
      <p className="text-xs text-muted">{t('sequentialHint')}</p>
      <fieldset className="flex flex-col gap-2" disabled={disabled || busy}>
        <legend className="text-xs text-muted">{t('variantProfiles')}</legend>
        {profiles.map((profile) => (
          <label key={profile.key} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={picked.has(profile.key)}
              onChange={() => {
                const next = new Set(picked);
                if (next.has(profile.key)) next.delete(profile.key);
                else next.add(profile.key);
                setPicked(next);
              }}
            />
            {profile.key} · {profile.width}×{profile.height}
          </label>
        ))}
      </fieldset>
      <div className="flex gap-2">
        <Button
          onClick={() => void run()}
          loading={busy}
          disabled={disabled || !revisionId || picked.size === 0}
        >
          {t('startExport')}
        </Button>
        {busy ? (
          <Button variant="secondary" onClick={cancel}>
            {t('cancelExport')}
          </Button>
        ) : null}
      </div>
      {draftId && lastExportId ? (
        <Button variant="secondary" onClick={() => void bind()} disabled={busy}>
          {t('bindAndPublish')}
        </Button>
      ) : null}
    </section>
  );
}
