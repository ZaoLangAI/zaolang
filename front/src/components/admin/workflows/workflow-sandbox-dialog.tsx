'use client';

import { useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import {
  SandboxRunInspector,
  type SandboxTraceStep,
} from '@/components/admin/workflows/sandbox-run-inspector';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { adminApi } from '@/lib/api/admin-client';
import type { WorkflowGraphJson } from '@/lib/api/admin-types';
import { newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import { useAdminJobStream } from '@/lib/use-admin-job-stream';

export type { SandboxTraceStep };

const TIERS = ['preview', 'standard', 'cinematic'] as const;
type Source = 'draft' | 'published';

// `image_to_image` deliberately excluded — a reference is optional there,
// the prompt is what's mandatory (see backend `canonical_operation`).
const REFERENCE_OPS = new Set(['image_to_video', 'video_to_video']);
const VIDEO_OPS = new Set(['text_to_video', 'image_to_video', 'video_to_video']);
const VIDEO_DURATIONS = Array.from({ length: 12 }, (_, index) => index + 4);
const DEFAULT_VIDEO_DURATION = 8;
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

/** Best-effort parse of the freeform params textarea — used only to preview
 * which operation a dry-run will route as; `run()` re-parses for real and
 * surfaces JSON errors properly. */
function tryParseParams(paramsText: string): Record<string, unknown> {
  if (!paramsText.trim()) return {};
  try {
    const parsed = JSON.parse(paramsText) as unknown;
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/** The workflow editor merges `text_to_image`/`image_to_image` into one
 * "图片创作" tab (see `WORKFLOW_EDITOR_OPERATIONS`) since they share a graph —
 * attaching `reference_asset_ids` is what turns a dry-run into an edit, the
 * same derivation the consumer studio does in `generation-studio.tsx`. This
 * only matters for provider-capability routing (`execute_route_score` keys
 * off the literal job operation); the graph itself is identical either way. */
function deriveSandboxOperation(operation: string, params: Record<string, unknown>): string {
  if (operation !== 'text_to_image') return operation;
  const refs = params.reference_asset_ids;
  return Array.isArray(refs) && refs.length > 0 ? 'image_to_image' : operation;
}

/**
 * Sandbox try-it dialog: form on the left, live node stream and final
 * preview on the right. Submits a real `GenerationJob` (`origin=sandbox`).
 */
export function WorkflowSandboxDialog({
  open,
  operation,
  assetKind,
  draftGraph,
  onClose,
  onTrace,
}: {
  open: boolean;
  operation: string;
  /** Injected into `params.asset_kind` on run — see `operationHasAssetKinds`. */
  assetKind?: string | null;
  draftGraph: WorkflowGraphJson;
  onClose: () => void;
  onTrace?: (trace: SandboxTraceStep[] | null) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const [source, setSource] = useState<Source>('draft');
  const [prompt, setPrompt] = useState('');
  const [qualityTier, setQualityTier] = useState<string>('standard');
  const [durationSeconds, setDurationSeconds] = useState(DEFAULT_VIDEO_DURATION);
  const [paramsText, setParamsText] = useState('');
  const [paramsError, setParamsError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const stream = useAdminJobStream(jobId);
  const jobStatus = stream.detail?.status ?? stream.events.at(-1)?.status ?? null;
  const inFlight = Boolean(jobId) && (jobStatus == null || !TERMINAL.has(jobStatus));

  const derivedOperation = useMemo(
    () => deriveSandboxOperation(operation, tryParseParams(paramsText)),
    [operation, paramsText],
  );

  const run = async () => {
    let params: Record<string, unknown> = {};
    if (paramsText.trim()) {
      try {
        const parsed = JSON.parse(paramsText) as unknown;
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          throw new Error('not an object');
        }
        params = parsed as Record<string, unknown>;
        setParamsError(null);
      } catch {
        setParamsError(t('dryRunParamsInvalid'));
        return;
      }
    }
    if (VIDEO_OPS.has(operation)) {
      params = { ...params, duration_seconds: durationSeconds };
    }
    if (assetKind) {
      params = { ...params, asset_kind: assetKind };
    }
    const effectiveOperation = deriveSandboxOperation(operation, params);

    setBusy(true);
    setError(null);
    setJobId(null);
    onTrace?.(null);
    try {
      const outcome = await adminApi.post<{ job_id: string }>(
        `/v1/admin/workflow-templates/${effectiveOperation}/sandbox-run`,
        {
          prompt,
          quality_tier: qualityTier,
          params,
          graph: source === 'draft' ? draftGraph : undefined,
        },
        { idempotencyKey: newIdempotencyKey() },
      );
      setJobId(outcome.job_id);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="xl"
      title={t('dryRun')}
      description={t('dryRunDesc')}
      footer={
        <Button
          loading={busy}
          disabled={prompt.trim().length === 0 || inFlight}
          onClick={() => void run()}
        >
          {t('runDryRun')}
        </Button>
      }
    >
      <div className="grid min-h-[28rem] gap-6 lg:grid-cols-2 lg:items-start lg:gap-8">
        <div className="flex flex-col gap-4">
          {assetKind ? (
            <p className="text-xs text-muted">{t('dryRunAssetKindHint', { kind: assetKind })}</p>
          ) : null}
          <Select
            label={t('dryRunSource')}
            value={source}
            hint={source === 'draft' ? t('dryRunSourceDraftHint') : undefined}
            onChange={(event) => setSource(event.target.value as Source)}
            options={[
              { value: 'draft', label: t('dryRunSourceDraft') },
              { value: 'published', label: t('dryRunSourcePublished') },
            ]}
          />
          <TextArea
            label={t('dryRunPrompt')}
            value={prompt}
            maxLength={2000}
            className="min-h-24"
            onChange={(event) => setPrompt(event.target.value)}
          />
          <Select
            label={t('dryRunQualityTier')}
            value={qualityTier}
            onChange={(event) => setQualityTier(event.target.value)}
            options={TIERS.map((tier) => ({ value: tier, label: tier }))}
          />
          {VIDEO_OPS.has(operation) ? (
            <Select
              label={t('dryRunDuration')}
              hint={t('dryRunDurationHint')}
              value={String(durationSeconds)}
              onChange={(event) => setDurationSeconds(Number(event.target.value))}
              options={VIDEO_DURATIONS.map((value) => ({
                value: String(value),
                label: t('dryRunDurationSeconds', { count: value }),
              }))}
            />
          ) : null}
          <TextArea
            label={t('dryRunParams')}
            hint={
              REFERENCE_OPS.has(operation)
                ? t('dryRunParamsHintReference')
                : operation === 'text_to_image'
                  ? t('dryRunParamsHintImageCreation')
                  : operation === 'image_to_image'
                    ? t('dryRunParamsHintOptionalReference')
                    : VIDEO_OPS.has(operation)
                      ? t('dryRunParamsHintVideo')
                      : t('dryRunParamsHint')
            }
            value={paramsText}
            maxLength={2000}
            className="min-h-20 font-mono text-xs"
            error={paramsError ?? undefined}
            onChange={(event) => {
              setParamsText(event.target.value);
              setParamsError(null);
            }}
          />
          {operation === 'text_to_image' ? (
            <p className="text-xs text-muted">
              {derivedOperation === 'image_to_image'
                ? t('dryRunRouteAsImageToImage')
                : t('dryRunRouteAsTextToImage')}
            </p>
          ) : null}
          <p className="text-xs text-muted">{t('dryRunCreditsHint')}</p>
          {error ? <ErrorNotice title={error} /> : null}
        </div>

        <div className="lg:border-l lg:border-border lg:pl-8">
          <SandboxRunInspector
            jobId={jobId}
            events={stream.events}
            detail={stream.detail}
            liveThinking={stream.liveThinking}
            reconnecting={stream.reconnecting}
            idleLabel={t('dryRunIdle')}
            onTrace={onTrace}
          />
        </div>
      </div>
    </Dialog>
  );
}
