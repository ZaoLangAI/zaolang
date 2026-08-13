'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, Switch, TextArea } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { adminApi } from '@/lib/api/admin-client';
import type {
  WorkflowDryRunResult,
  WorkflowDryRunStepView,
  WorkflowGraphJson,
} from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

const TIERS = ['preview', 'standard', 'cinematic'] as const;
type Source = 'draft' | 'published';

const REFERENCE_OPS = new Set(['image_to_image', 'image_to_video', 'video_to_video']);

/**
 * Sandbox try-it: runs a graph through `WorkflowRunner` with `dry_run=True`.
 *
 * Defaults to the canvas's unpublished draft — the whole reason this exists
 * is the edit → run → look loop the product is built around; running only
 * the already-published graph would mean publishing an edit before ever
 * seeing it execute. "跑已发布生效图" stays available for checking today's
 * real behaviour without whatever is mid-edit on the canvas. Either way, the
 * graph is validated exactly like a publish before it runs (see
 * `dry_run_workflow_template`'s docstring), and never becomes a
 * `GenerationWorkflowTemplate` row — see its docstring for exactly what
 * stays real (the four agent nodes) versus stubbed (billing, and the paid
 * provider call unless the operator opts into `live_provider`).
 */
export function WorkflowDryRunDialog({
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
  /** Lifted so the canvas can highlight the path this run walked. */
  onTrace?: (trace: WorkflowDryRunStepView[] | null) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const [source, setSource] = useState<Source>('draft');
  const [prompt, setPrompt] = useState('');
  const [qualityTier, setQualityTier] = useState<string>('standard');
  const [paramsText, setParamsText] = useState('');
  const [paramsError, setParamsError] = useState<string | null>(null);
  const [liveProvider, setLiveProvider] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WorkflowDryRunResult | null>(null);

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

    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const outcome = await adminApi.post<WorkflowDryRunResult>(
        `/v1/admin/workflow-templates/${operation}/dry-run`,
        {
          prompt,
          quality_tier: qualityTier,
          params,
          live_provider: liveProvider,
          graph: source === 'draft' ? draftGraph : undefined,
        },
      );
      setResult(outcome);
      onTrace?.(outcome.trace ?? null);
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
      size="lg"
      title={t('dryRun')}
      description={t('dryRunDesc')}
      footer={
        <Button loading={busy} disabled={prompt.trim().length === 0} onClick={() => void run()}>
          {t('runDryRun')}
        </Button>
      }
    >
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
        <TextArea
          label={t('dryRunParams')}
          hint={
            REFERENCE_OPS.has(operation) ? t('dryRunParamsHintReference') : t('dryRunParamsHint')
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
        <Switch
          checked={liveProvider}
          onChange={setLiveProvider}
          label={t('dryRunLiveProvider')}
          description={t('dryRunLiveProviderHint')}
        />

        {error ? <ErrorNotice title={error} /> : null}

        {result ? (
          <div className="flex flex-col gap-3 border-t border-border pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={result.status === 'succeeded' ? 'success' : 'danger'}>
                {result.status}
              </Badge>
              {result.failure_code ? (
                <span className="font-mono text-xs text-muted">{result.failure_code}</span>
              ) : null}
              {(result.trace?.length ?? 0) > 0 ? (
                <span className="text-xs text-muted">{t('dryRunReplayHint')}</span>
              ) : null}
            </div>

            {result.error_detail ? (
              <ErrorNotice title={t('dryRunErrorDetail')} detail={result.error_detail} />
            ) : null}

            {result.preview_url ? (
              <div className="overflow-hidden rounded-[var(--radius-sm)] border border-border">
                {result.mime_type?.startsWith('audio/') ? (
                  <audio src={result.preview_url} controls className="w-full p-3" />
                ) : result.mime_type?.startsWith('video/') ? (
                  <video src={result.preview_url} controls className="w-full bg-black" />
                ) : (
                  // Native img: sandbox preview URLs are short-lived MinIO
                  // signatures, not the Next image optimizer's allowlist.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={result.preview_url}
                    alt={t('dryRunPreview')}
                    className="max-h-80 w-full object-contain"
                  />
                )}
              </div>
            ) : null}

            <ol className="flex flex-col gap-1.5">
              {(result.trace ?? []).map((step, index) => (
                <li
                  key={`${step.node_id}-${index}`}
                  className="flex flex-col gap-1 rounded-[var(--radius-sm)] border border-border px-3 py-1.5 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                      <span className="tabular text-muted">{index + 1}.</span>
                      <span className="font-medium">{step.node_id}</span>
                      <span className="font-mono text-muted">{step.node_type}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      {step.duration_ms != null ? (
                        <span className="tabular text-muted">{step.duration_ms}ms</span>
                      ) : null}
                      {step.agent_run_id ? (
                        // Dry-run `AgentRun` rows are real, but their `job_id`
                        // is null (no `GenerationJob` exists to point at), so
                        // this can't link into `/admin/jobs` — shown as a
                        // copyable id instead via the native tooltip.
                        <span title={step.agent_run_id}>
                          <Badge tone="primary">{t('agentRunTrace')}</Badge>
                        </span>
                      ) : null}
                      <Badge tone="neutral">{step.port}</Badge>
                    </span>
                  </div>
                  {step.summary ? <p className="text-muted">{step.summary}</p> : null}
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
