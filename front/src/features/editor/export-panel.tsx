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
import { runStructuralPrecheck, type PrecheckIssueKind } from './engine/export-precheck';
import { SequentialExportRunner } from './engine/export-runner';
import {
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type ExportProgress,
  type ResolvedAsset,
} from './engine/ports';
import { ExportPrecheckPanel } from './export-precheck-panel';
import { canvasOrientation, pickDefaultProfileKey, profileOrientationKey } from './export-profile';

const PRECHECK_SAMPLE_COUNT = 5;

export function ExportPanel({
  revisionId,
  document,
  assets,
  durationTicks,
  draftId,
  disabled,
  profiles,
  defaultProfile,
}: {
  revisionId: string | null;
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  durationTicks: number;
  draftId: string | null;
  disabled: boolean;
  profiles: ShortformProfile[];
  defaultProfile: string | null;
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const router = useRouter();
  const stageLabel: Record<ExportProgress['stage'], string> = {
    encoding: t('exportStage.encoding'),
    uploading: t('exportStage.uploading'),
    verifying: t('exportStage.verifying'),
  };
  const defaultKey = pickDefaultProfileKey(profiles, document.canvas, defaultProfile);
  const selectionSeed = `${defaultKey ?? ''}:${canvasOrientation(document.canvas)}`;
  const [picked, setPicked] = useState<Set<string>>(() => new Set(defaultKey ? [defaultKey] : []));
  const [pickedSeed, setPickedSeed] = useState(selectionSeed);
  if (pickedSeed !== selectionSeed) {
    setPickedSeed(selectionSeed);
    setPicked(new Set(defaultKey ? [defaultKey] : []));
  }
  const [busy, setBusy] = useState(false);
  const [lastExportId, setLastExportId] = useState<string | null>(null);
  // Walkthrough finding: the loop below already had `progress.percent`/
  // `progress.stage` in hand (sent to the backend as an export heartbeat)
  // but only surfaced a generic button `loading` spinner — no percent, no
  // stage. This mirrors that same data into the UI instead of discarding it.
  const [progress, setProgress] = useState<Pick<ExportProgress, 'percent' | 'stage'> | null>(null);
  // The implicit (metadata) AI label is always written by the runner; this
  // is the visible one. On by default — 《人工智能生成合成内容标识办法》 asks
  // for an explicit label on synthetic video, so turning it off is a choice.
  const [aiLabel, setAiLabel] = useState(true);
  const runner = useMemo(() => new SequentialExportRunner(), []);
  const controllerRef = useRef<AbortController | null>(null);
  const claimedExportIdRef = useRef<string | null>(null);

  // Walkthrough finding: an export only ever surfaced problems (a blank
  // canvas, a keyframed pan that drifted a clip fully off-frame) after a
  // full encode/upload round-trip. This runs the same `resolveFrame` truth
  // the export itself will use across a handful of sampled ticks up front,
  // so those two failure modes show up before the user spends the time.
  const precheck = useMemo(
    () => runStructuralPrecheck(document, durationTicks, PRECHECK_SAMPLE_COUNT),
    [document, durationTicks],
  );
  const issueKey = precheck.issues.map((issue) => `${issue.kind}:${issue.atTicks}`).join(',');
  // "Adjust state during render" (React's documented pattern for resetting
  // derived state on a prop change) rather than an effect: an edit that
  // fixes/introduces an issue must re-arm this gate on the very render that
  // shows the new issue list, not one render later.
  const [acknowledged, setAcknowledged] = useState({ key: issueKey, checked: false });
  if (acknowledged.key !== issueKey) setAcknowledged({ key: issueKey, checked: false });
  const issuesBlockExport = precheck.issues.length > 0 && !acknowledged.checked;
  const issueLabel: Record<PrecheckIssueKind, string> = {
    blank_frame: t('exportPrecheckBlankFrame'),
    clip_off_canvas: t('exportPrecheckClipOffCanvas'),
  };

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
      const variant = variants.find((item) => item.id === claimed.variant_id) ?? variants[0];
      const spec = {
        profile_key: variant?.profile_key ?? claimed.variant_id,
        width: variant?.width ?? 1080,
        height: variant?.height ?? 1920,
        fps_num: 30,
        fps_den: 1,
        format: 'mp4' as const,
        caption_language: null,
        caption_mode: 'burned' as const,
        max_duration_ticks: durationTicks,
      };
      const renderOptions = aiLabel ? { aiLabel: { text: t('exportAiLabelText') } } : {};
      let blob: Blob | undefined;
      for await (const step of runner.export(
        spec,
        document,
        assets,
        controller.signal,
        renderOptions,
      )) {
        await editorApi.heartbeatExport(claimed.id, step.percent, step.stage);
        setProgress({ percent: step.percent, stage: step.stage });
        blob = step.blob ?? blob;
      }
      if (!blob || blob.size === 0) throw new Error('empty_export');
      setProgress({ percent: 100, stage: 'uploading' });
      await editorApi.heartbeatExport(claimed.id, 100, 'uploading');
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
      setProgress({ percent: 100, stage: 'verifying' });
      await editorApi.heartbeatExport(claimed.id, 100, 'verifying');
      const done = await editorApi.completeExport(claimed.id, presigned.upload_session_id);
      setLastExportId(done.id);
      notify(t('exportDone'), 'success');
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        notify(t('exportCancelled'), 'info');
      } else {
        const exportId = claimedExportIdRef.current;
        if (exportId) {
          void editorApi
            .failExport(
              exportId,
              'export_failed',
              isApiError(error) ? error.message : t('commandFailed'),
            )
            .catch(() => undefined);
        }
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      }
    } finally {
      setBusy(false);
      setProgress(null);
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
    if (!lastExportId) return;
    setBusy(true);
    try {
      const bound = await editorApi.ensureBoundDraft(lastExportId, draftId);
      router.push(`/publish/${bound.draft_id}`);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted">{t('exportHint')}</p>
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
            {profile.key} · {profile.aspect_ratio} · {t(profileOrientationKey(profile))} ·{' '}
            {profile.width}×{profile.height}
          </label>
        ))}
      </fieldset>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={aiLabel}
          disabled={disabled || busy}
          onChange={(event) => setAiLabel(event.target.checked)}
          className="mt-1"
        />
        <span>
          {t('exportAiLabel')}
          <span className="block text-xs text-muted">{t('exportAiLabelHint')}</span>
        </span>
      </label>
      <div className="flex flex-col gap-2">
        <p className="text-xs text-muted">{t('exportPrecheckTitle')}</p>
        <ExportPrecheckPanel document={document} assets={assets} samples={precheck.samples} />
        {precheck.issues.length > 0 ? (
          <div className="flex flex-col gap-1.5 rounded-[var(--radius-sm)] border border-danger/40 bg-danger/5 p-2">
            <ul className="flex flex-col gap-0.5 text-xs text-danger">
              {precheck.issues.map((issue, index) => (
                <li key={index}>
                  {(issue.atTicks / TICKS_PER_SECOND).toFixed(1)}s · {issueLabel[issue.kind]}
                </li>
              ))}
            </ul>
            <label className="flex items-center gap-2 text-xs text-text">
              <input
                type="checkbox"
                checked={acknowledged.checked}
                onChange={(event) =>
                  setAcknowledged({ key: issueKey, checked: event.target.checked })
                }
              />
              {t('exportPrecheckAcknowledge')}
            </label>
          </div>
        ) : null}
      </div>
      <div className="flex gap-2">
        <Button
          onClick={() => void run()}
          loading={busy}
          disabled={disabled || !revisionId || picked.size === 0 || issuesBlockExport}
        >
          {t('startExport')}
        </Button>
        {busy ? (
          <Button variant="secondary" onClick={cancel}>
            {t('cancelExport')}
          </Button>
        ) : null}
      </div>
      {busy && progress ? (
        <div className="flex flex-col gap-1">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-soft">
            <div
              className="h-full rounded-full bg-primary transition-[width]"
              style={{ width: `${Math.min(100, Math.max(0, progress.percent))}%` }}
            />
          </div>
          <p className="text-xs text-muted">
            {stageLabel[progress.stage]} · {Math.round(progress.percent)}%
          </p>
        </div>
      ) : null}
      {lastExportId ? (
        <Button variant="secondary" onClick={() => void bind()} disabled={busy}>
          {t('bindAndPublish')}
        </Button>
      ) : null}
    </div>
  );
}
