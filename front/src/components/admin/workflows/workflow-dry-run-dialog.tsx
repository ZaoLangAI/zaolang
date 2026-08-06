'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { adminApi } from '@/lib/api/admin-client';
import type { WorkflowDryRunResult } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

const TIERS = ['preview', 'standard', 'cinematic'] as const;

/**
 * Sandbox try-it: runs the operation's *active published* graph — not
 * whatever is unsaved on the canvas — through `WorkflowRunner` with
 * `dry_run=True`. Publish first to try out canvas edits; see
 * `workflow_templates.dry_run_workflow_template`'s docstring for exactly
 * what stays real (the four agent nodes) versus stubbed (billing, the paid
 * provider call).
 */
export function WorkflowDryRunDialog({
  open,
  operation,
  onClose,
}: {
  open: boolean;
  operation: string;
  onClose: () => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const [prompt, setPrompt] = useState('');
  const [qualityTier, setQualityTier] = useState<string>('standard');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WorkflowDryRunResult | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const outcome = await adminApi.post<WorkflowDryRunResult>(
        `/v1/admin/workflow-templates/${operation}/dry-run`,
        { prompt, quality_tier: qualityTier },
      );
      setResult(outcome);
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
            </div>

            <ol className="flex flex-col gap-1.5">
              {(result.trace ?? []).map((step, index) => (
                <li
                  key={`${step.node_id}-${index}`}
                  className="flex items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-border px-3 py-1.5 text-xs"
                >
                  <span className="flex items-center gap-2">
                    <span className="tabular text-muted">{index + 1}.</span>
                    <span className="font-medium">{step.node_id}</span>
                    <span className="font-mono text-muted">{step.node_type}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {step.agent_run_id ? (
                      <Badge tone="primary">{t('agentRunTrace')}</Badge>
                    ) : null}
                    <Badge tone="neutral">{step.port}</Badge>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
