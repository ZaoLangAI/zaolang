'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useState } from 'react';

import { AwaitingInputPanel } from '@/components/job/awaiting-input-panel';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { Locale } from '@/i18n/routing';
import { adminApi } from '@/lib/api/admin-client';
import type { AdminJobDetail, WorkflowGraphJson } from '@/lib/api/admin-types';
import { newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { JobStatus } from '@/lib/api/types';
import { formatDateTime, formatNumber } from '@/lib/format';
import { useAdminJobStream, type AdminStreamedEvent } from '@/lib/use-admin-job-stream';

const TIERS = ['preview', 'standard', 'cinematic'] as const;
type Source = 'draft' | 'published';

const REFERENCE_OPS = new Set(['image_to_image', 'image_to_video', 'video_to_video']);
const VIDEO_OPS = new Set(['text_to_video', 'image_to_video', 'video_to_video']);
const VIDEO_DURATIONS = Array.from({ length: 12 }, (_, index) => index + 4);
const DEFAULT_VIDEO_DURATION = 8;
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

export type SandboxTraceStep = { node_id: string; port?: string | null };

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
  const tJob = useTranslations('job');
  const tJobs = useTranslations('adminJobs');
  const locale = useLocale() as Locale;
  const [source, setSource] = useState<Source>('draft');
  const [prompt, setPrompt] = useState('');
  const [qualityTier, setQualityTier] = useState<string>('standard');
  const [durationSeconds, setDurationSeconds] = useState(DEFAULT_VIDEO_DURATION);
  const [paramsText, setParamsText] = useState('');
  const [paramsError, setParamsError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [inspectDetail, setInspectDetail] = useState<AdminJobDetail | null>(null);

  const stream = useAdminJobStream(jobId);
  const detail = inspectDetail ?? stream.detail;

  const trace = useMemo(() => {
    const steps: SandboxTraceStep[] = [];
    const seen = new Set<string>();
    for (const event of stream.events) {
      if (!event.node_id || seen.has(event.node_id)) continue;
      seen.add(event.node_id);
      steps.push({ node_id: event.node_id });
    }
    return steps;
  }, [stream.events]);

  useEffect(() => {
    onTrace?.(trace.length ? trace : null);
  }, [trace, onTrace]);

  useEffect(() => {
    if (!jobId || !selectedNodeId) return;
    let cancelled = false;
    adminApi
      .get<AdminJobDetail>(`/v1/admin/jobs/${jobId}`)
      .then((data) => {
        if (!cancelled) setInspectDetail(data);
      })
      .catch(() => {
        if (!cancelled) setInspectDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, selectedNodeId, stream.events.length]);

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
    setSelectedNodeId(null);
    setInspectDetail(null);
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

  const inspect = selectedNodeId ? inspectNode(selectedNodeId, detail, stream.events) : null;
  const previewUrl = stream.detail?.preview_url ?? detail?.preview_url ?? null;
  const mimeType = stream.detail?.mime_type ?? detail?.mime_type ?? null;
  const latestEvent = stream.events.at(-1);
  const jobStatus = (stream.detail?.status ?? latestEvent?.status ?? null) as JobStatus | null;
  const inFlight = Boolean(jobId) && (jobStatus == null || !TERMINAL.has(jobStatus));
  const asyncTask = inFlight ? (stream.detail?.async_task ?? null) : null;

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

        <div className="flex flex-col gap-3 lg:border-l lg:border-border lg:pl-8">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
              {t('dryRunStreaming')}
            </h3>
            {jobStatus ? (
              <Badge
                tone={
                  jobStatus === 'succeeded'
                    ? 'success'
                    : jobStatus === 'awaiting_input'
                      ? 'amber'
                      : TERMINAL.has(jobStatus)
                        ? 'danger'
                        : 'primary'
                }
              >
                {tJob(jobStatus)}
              </Badge>
            ) : null}
          </div>

          {!jobId ? (
            <p className="text-xs text-muted">{t('dryRunIdle')}</p>
          ) : stream.events.length === 0 ? (
            <div className="flex items-center gap-2 text-xs text-muted">
              <Spinner />
              {stream.reconnecting ? tAdmin('loadFailed') : t('dryRunQueued')}
            </div>
          ) : (
            <ol className="flex flex-col gap-1.5">
              {stream.events.map((event) => {
                const active = event.node_id != null && event.node_id === selectedNodeId;
                return (
                  <li key={event.sequence}>
                    <button
                      type="button"
                      disabled={!event.node_id}
                      onClick={() => event.node_id && setSelectedNodeId(event.node_id)}
                      className={`flex w-full flex-col gap-0.5 rounded-[var(--radius-sm)] border px-3 py-1.5 text-left text-xs ${
                        active
                          ? 'border-accent bg-accent/10'
                          : event.status === 'awaiting_input'
                            ? 'border-amber/40 bg-amber/5'
                            : 'border-border hover:border-accent/40'
                      } ${event.node_id ? 'cursor-pointer' : 'cursor-default'}`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="font-medium">{event.node_id ?? event.event_type}</span>
                        <span className="tabular text-muted">{event.progress}%</span>
                      </span>
                      <span className="text-muted">{event.message}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          )}

          {inFlight && latestEvent ? (
            <div className="flex flex-col gap-1.5 rounded-[var(--radius-sm)] border border-border p-3 text-xs">
              <div className="flex items-center gap-2 text-muted">
                <Spinner />
                {t('dryRunWaitingRender')}
              </div>
              <p>
                <span className="text-muted">{t('dryRunLatest')}</span> {latestEvent.message}
              </p>
              <p className="tabular text-muted">
                {tJob('progress', { percent: latestEvent.progress })}
              </p>
            </div>
          ) : null}

          {asyncTask ? (
            <div className="flex flex-col gap-1.5 rounded-[var(--radius-sm)] border border-amber/40 bg-amber/8 p-3 text-xs">
              <p className="font-medium">{tJobs('asyncTask')}</p>
              <p className="text-muted">{tJobs('asyncTaskHint')}</p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                <dt className="text-muted">{tJobs('asyncTaskNode')}</dt>
                <dd>{asyncTask.node_id}</dd>
                <dt className="text-muted">{tJobs('asyncTaskProvider')}</dt>
                <dd>{asyncTask.provider_label ?? asyncTask.capability_name}</dd>
                <dt className="text-muted">{tJobs('asyncTaskExternalId')}</dt>
                <dd className="font-mono">{asyncTask.external_task_id}</dd>
                <dt className="text-muted">{tJobs('asyncTaskPolls')}</dt>
                <dd>{formatNumber(asyncTask.poll_count, locale)}</dd>
                <dt className="text-muted">{tJobs('asyncTaskDeadline')}</dt>
                <dd>{formatDateTime(asyncTask.deadline_at, locale)}</dd>
              </dl>
            </div>
          ) : null}

          {jobId && jobStatus === 'awaiting_input' ? (
            <AwaitingInputPanel jobId={jobId} client={adminApi} basePath="/v1/admin/jobs" />
          ) : null}

          {inspect ? (
            <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-border p-3">
              <p className="text-xs font-medium">{t('dryRunSelectNode')}</p>
              {inspect.systemPrompt || inspect.userPrompt || inspect.mediaPrompt ? (
                <div className="flex flex-col gap-1">
                  <span className="text-[11px] uppercase tracking-wide text-muted">
                    {t('dryRunNodeInput')}
                  </span>
                  {inspect.systemPrompt ? (
                    <PromptBlock label={t('dryRunSystemPrompt')} text={inspect.systemPrompt} />
                  ) : null}
                  {inspect.userPrompt ? (
                    <PromptBlock label={t('dryRunUserPrompt')} text={inspect.userPrompt} />
                  ) : null}
                  {inspect.mediaPrompt ? (
                    <PromptBlock label={t('dryRunPrompt')} text={inspect.mediaPrompt} />
                  ) : null}
                </div>
              ) : (
                <p className="text-xs text-muted">{t('dryRunNoInput')}</p>
              )}
              <div className="flex flex-col gap-1">
                <span className="text-[11px] uppercase tracking-wide text-muted">
                  {t('dryRunNodeOutput')}
                </span>
                {inspect.output ? (
                  <pre className="max-h-48 overflow-auto rounded-[var(--radius-sm)] bg-muted/30 p-2 font-mono text-[11px] whitespace-pre-wrap">
                    {inspect.output}
                  </pre>
                ) : (
                  <p className="text-xs text-muted">{t('dryRunNoOutput')}</p>
                )}
              </div>
            </div>
          ) : jobId ? (
            <p className="text-xs text-muted">{t('dryRunSelectNode')}</p>
          ) : null}

          {previewUrl ? (
            <div className="overflow-hidden rounded-[var(--radius-sm)] border border-border">
              {mimeType?.startsWith('audio/') ? (
                <audio src={previewUrl} controls className="w-full p-3" />
              ) : mimeType?.startsWith('video/') ? (
                <video src={previewUrl} controls className="w-full bg-black" />
              ) : (
                // Native img: sandbox preview URLs are short-lived MinIO signatures.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={previewUrl}
                  alt={t('dryRunPreview')}
                  className="max-h-80 w-full object-contain"
                />
              )}
            </div>
          ) : null}
        </div>
      </div>
    </Dialog>
  );
}

function PromptBlock({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted">{label}</p>
      <pre className="mt-0.5 max-h-36 overflow-auto rounded-[var(--radius-sm)] bg-muted/30 p-2 font-mono text-[11px] whitespace-pre-wrap">
        {text}
      </pre>
    </div>
  );
}

function inspectNode(
  nodeId: string,
  detail: AdminJobDetail | null,
  events: AdminStreamedEvent[],
): {
  systemPrompt: string | null;
  userPrompt: string | null;
  mediaPrompt: string | null;
  output: string | null;
} {
  const runs = detail?.agent_runs?.filter((item) => item.node_id === nodeId) ?? [];
  const run = runs.at(-1);
  const input = run?.input_json;
  const systemPrompt =
    input && typeof input.system_prompt === 'string' ? input.system_prompt : null;
  const userPrompt = input && typeof input.user_prompt === 'string' ? input.user_prompt : null;
  const payloadEvent = [...events].reverse().find((event) => event.node_id === nodeId);
  const payload = detail?.events?.find((event) => event.node_id === nodeId)?.payload;
  const mediaPrompt = payload && typeof payload.prompt === 'string' ? payload.prompt : null;
  const output = runs.length
    ? runs
        .map((item) => {
          const slot = item.prompt_slot ? `${item.prompt_slot}\n` : '';
          return `${slot}${JSON.stringify(item.output_json ?? {}, null, 2)}`;
        })
        .join('\n\n')
    : payload
      ? JSON.stringify(payload, null, 2)
      : payloadEvent
        ? payloadEvent.message
        : null;
  return { systemPrompt, userPrompt, mediaPrompt, output };
}
