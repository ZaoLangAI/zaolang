'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

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

const REFERENCE_OPS = new Set(['image_to_image', 'image_to_video', 'video_to_video']);
const VIDEO_OPS = new Set(['text_to_video', 'image_to_video', 'video_to_video']);
const VIDEO_DURATIONS = Array.from({ length: 12 }, (_, index) => index + 4);
const DEFAULT_VIDEO_DURATION = 8;
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

/**
 * Sandbox try-it dialog: form on the left, live node stream and final
 * preview on the right. Submits a real `GenerationJob` (`origin=sandbox`).
 */
export function WorkflowSandboxDialog({
  open,
  operation,
  draftGraph,
  onClose,
  onTrace,
}: {
  open: boolean;
  operation: string;
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

    setBusy(true);
    setError(null);
    setJobId(null);
    onTrace?.(null);
    try {
      const outcome = await adminApi.post<{ job_id: string }>(
        `/v1/admin/workflow-templates/${operation}/sandbox-run`,
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
          <p className="text-xs text-muted">{t('dryRunCreditsHint')}</p>
          {error ? <ErrorNotice title={error} /> : null}
        </div>

        <div className="lg:border-l lg:border-border lg:pl-8">
          <SandboxRunInspector
            jobId={jobId}
            events={stream.events}
            detail={stream.detail}
            reconnecting={stream.reconnecting}
            idleLabel={t('dryRunIdle')}
            onTrace={onTrace}
          />
        </div>
      </div>
    </Dialog>
  );
}
