'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAdminSession } from '@/components/admin/admin-session-provider';
import { DangerConfirm } from '@/components/admin/danger-confirm';
import { DataTable, type Column } from '@/components/admin/data-table';
import { DetailDrawer, DetailList } from '@/components/admin/detail-drawer';
import { DurationBars, type DurationSegment } from '@/components/admin/duration-bars';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { RoutingReplayTable } from '@/components/admin/jobs/routing-replay-table';
import { WorkflowSteps } from '@/components/admin/jobs/workflow-steps';
import { Timeline, type TimelineEntry } from '@/components/admin/timeline';
import { Button } from '@/components/ui/button';
import { Badge, type BadgeTone } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale } from '@/i18n/routing';
import { atLeast } from '@/lib/admin/rbac';
import { useAdminList } from '@/lib/admin/use-admin-list';
import { adminApi } from '@/lib/api/admin-client';
import type {
  AdminJob,
  AdminJobDetail,
  LogEntry,
  Page,
  WorkflowShape,
} from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';
import { useResource } from '@/lib/use-resource';

const STATUSES = [
  'created',
  'queued',
  'submitted',
  'running',
  'succeeded',
  'failed',
  'cancelled',
  'expired',
] as const;

const LOG_SOURCE_TONE: Record<string, BadgeTone> = {
  audit: 'primary',
  pipeline: 'danger',
  auth: 'neutral',
  rate_limit: 'amber',
  permission: 'amber',
};

/** A raw id kept out of the primary text, one hover away via `title`. */
function IdWithTooltip({ primary, id }: { primary: string; id: string }) {
  return (
    <span className="font-mono text-xs" title={id}>
      {primary}
    </span>
  );
}

export function JobsConsole() {
  const t = useTranslations('adminJobs');
  const tAdmin = useTranslations('admin');
  const tJob = useTranslations('job');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const { role } = useAdminSession();

  const list = useAdminList<AdminJob>('/v1/admin/jobs');
  // The filter bar edits this draft, not `list.filters` directly — a request
  // only goes out when the operator clicks "search" (or presses Enter),
  // never on every keystroke/checkbox toggle.
  const [draftFilters, setDraftFilters] = useState<Record<string, string>>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [danger, setDanger] = useState<'terminate' | null>(null);

  const canOperate = atLeast(role, 'operator');

  const columns: Array<Column<AdminJob>> = [
    {
      id: 'id',
      header: t('colId'),
      render: (row) => <span className="font-mono text-xs">{row.id}</span>,
    },
    {
      id: 'user',
      header: t('colUser'),
      render: (row) => (
        <IdWithTooltip
          primary={row.user_display_name ?? row.user_handle ?? row.user_id}
          id={row.user_id}
        />
      ),
    },
    {
      id: 'status',
      header: t('colStatus'),
      render: (row) => (
        <span className="flex items-center gap-1.5">
          <Badge
            tone={
              row.status === 'succeeded'
                ? 'success'
                : row.status === 'failed' || row.status === 'expired'
                  ? 'danger'
                  : row.status === 'cancelled'
                    ? 'neutral'
                    : 'primary'
            }
          >
            {tJob(row.status)}
          </Badge>
          {row.stuck ? <Badge tone="danger">{t('stuckBadge')}</Badge> : null}
        </span>
      ),
    },
    {
      id: 'operation',
      header: t('colOperation'),
      render: (row) => <span className="text-xs">{t(`operation.${row.operation}`)}</span>,
    },
    {
      id: 'tier',
      header: t('colTier'),
      render: (row) => <span className="text-xs">{t(`tier.${row.quality_tier}`)}</span>,
    },
    {
      id: 'credits',
      header: t('colCredits'),
      numeric: true,
      render: (row) =>
        `${formatNumber(row.actual_credits ?? row.quoted_credits, locale)}${row.actual_credits === null ? '*' : ''}`,
    },
    {
      id: 'provider',
      header: t('colProvider'),
      render: (row) =>
        row.provider ? (
          <IdWithTooltip primary={row.provider_label ?? row.provider} id={row.provider} />
        ) : (
          <span className="text-xs text-muted">—</span>
        ),
    },
    {
      id: 'created',
      header: t('colCreated'),
      render: (row) => (
        <span className="tabular whitespace-nowrap text-xs text-muted">
          {formatDateTime(row.created_at, locale)}
        </span>
      ),
    },
  ];

  const detail = useResource<AdminJobDetail>(openId ? `/v1/admin/jobs/${openId}` : null);
  const job = detail.data;
  // The pipeline shape depends on the job's operation (each operation has its
  // own configurable workflow template), so it's re-fetched per selected job.
  // Passing the job's own `workflow_template_id` asks for the exact graph it
  // pinned at submission/first run, not whatever is active for the operation
  // today — those two can diverge once someone republishes the template.
  const workflow = useResource<WorkflowShape>(
    job
      ? `/v1/admin/workflow?operation=${job.operation}${
          job.workflow_template_id ? `&template_id=${job.workflow_template_id}` : ''
        }`
      : null,
  );
  const relatedLogs = useResource<Page<LogEntry>>(
    openId ? `/v1/admin/logs?job_id=${openId}&limit=20` : null,
  );
  const attempts = job?.attempts ?? [];
  const agentRuns = job?.agent_runs ?? [];
  const events = job?.events ?? [];
  const logRows = relatedLogs.data?.items ?? [];

  // Each segment is the gap between two consecutive events, labelled by the
  // stage that just finished — "how long safety took before planning started".
  const durationSegments: DurationSegment[] = [];
  for (let index = 0; index < events.length - 1; index += 1) {
    const event = events[index];
    const next = events[index + 1];
    if (!event || !next) continue;
    const ms = Math.max(
      new Date(next.created_at).getTime() - new Date(event.created_at).getTime(),
      0,
    );
    const tone: DurationSegment['tone'] =
      next.status === 'failed' || next.status === 'expired'
        ? 'danger'
        : next.status === 'succeeded'
          ? 'success'
          : 'primary';
    durationSegments.push({
      key: `${event.sequence}-${next.sequence}`,
      label: event.event_type,
      ms,
      tone,
    });
  }

  const timeline: TimelineEntry[] = (job?.events ?? []).map((event) => ({
    id: String(event.sequence),
    at: event.created_at,
    label: event.message,
    detail: `${event.event_type} · ${event.progress}%`,
    code: event.internal_code ?? undefined,
    tone:
      event.status === 'succeeded'
        ? 'success'
        : event.status === 'failed' || event.status === 'expired'
          ? 'danger'
          : 'neutral',
  }));

  // The node the async task is suspended on, resolved to its declared label
  // so the section reads "waiting on <step>" rather than a bare node key.
  const asyncTaskStepLabel = job?.async_task
    ? (workflow.data?.steps.find((step) => step.key === job.async_task?.node_id)?.label ??
      job.async_task.node_id)
    : null;

  const act = async (action: 'requeue' | 'terminate', reason?: string) => {
    if (!openId) return;
    await adminApi.post(
      `/v1/admin/jobs/${openId}/${action}`,
      action === 'terminate' ? { reason, confirm: true, release_credits: true } : undefined,
    );
    notify(t(action === 'requeue' ? 'requeue' : 'terminate'), 'success');
    list.reload();
    setOpenId(null);
  };

  return (
    <div className="flex flex-col">
      <FilterBar
        filters={[
          {
            id: 'status',
            label: t('filterStatus'),
            kind: 'multiselect',
            options: STATUSES.map((value) => ({ value, label: tJob(value) })),
          },
          { id: 'user', label: t('filterUser'), kind: 'text', placeholder: t('filterUserPlaceholder') },
          {
            id: 'provider',
            label: t('colProvider'),
            kind: 'text',
            placeholder: t('filterProviderPlaceholder'),
          },
          { id: 'created', label: t('filterCreated'), kind: 'daterange' },
          {
            id: 'stuck_only',
            label: t('filterStuckOnly'),
            kind: 'select',
            options: [{ value: 'true', label: t('stuckBadge') }],
          },
        ]}
        values={draftFilters}
        onChange={(id, value) => setDraftFilters((current) => ({ ...current, [id]: value }))}
        onReset={() => {
          setDraftFilters({});
          list.resetFilters();
        }}
        onSearch={() => list.applyFilters(draftFilters)}
      >
        <Button size="sm" variant="secondary" onClick={list.reload}>
          {tAdmin('refresh')}
        </Button>
      </FilterBar>

      <div className="mt-3">
        <DataTable
          caption={t('title')}
          columns={columns}
          rows={list.rows}
          rowKey={(row) => row.id}
          loading={list.loading}
          failed={list.failed}
          activeKey={openId ?? undefined}
          onRowClick={(row) => setOpenId(row.id)}
        />
      </div>

      <Pager
        onPrev={list.prevPage}
        onNext={list.nextPage}
        hasPrev={list.hasPrev}
        hasNext={list.hasNext}
      />

      <DetailDrawer
        open={openId !== null}
        onClose={() => setOpenId(null)}
        title={openId ?? ''}
        subtitle={
          job
            ? [job.operation, job.quality_tier, workflow.data?.name].filter(Boolean).join(' · ')
            : undefined
        }
        footer={
          canOperate &&
          job &&
          !['succeeded', 'failed', 'cancelled', 'expired'].includes(job.status) ? (
            <>
              <Button size="sm" variant="secondary" onClick={() => void act('requeue')}>
                {t('requeue')}
              </Button>
              <Button size="sm" variant="danger" onClick={() => setDanger('terminate')}>
                {t('terminate')}
              </Button>
            </>
          ) : null
        }
      >
        {job ? (
          <div className="flex flex-col gap-6">
            <DetailList
              items={[
                {
                  label: t('colUser'),
                  value: (
                    <IdWithTooltip
                      primary={job.user_display_name ?? job.user_handle ?? job.user_id}
                      id={job.user_id}
                    />
                  ),
                },
                {
                  label: t('colStatus'),
                  value: (
                    <span className="flex items-center gap-1.5">
                      {tJob(job.status)}
                      {job.stuck ? <Badge tone="danger">{t('stuckBadge')}</Badge> : null}
                    </span>
                  ),
                },
                {
                  label: t('colCredits'),
                  value: `${formatNumber(job.quoted_credits, locale)} → ${
                    job.actual_credits == null ? '—' : formatNumber(job.actual_credits, locale)
                  }`,
                },
                {
                  label: t('colProvider'),
                  value: job.provider ? (
                    <IdWithTooltip primary={job.provider_label ?? job.provider} id={job.provider} />
                  ) : (
                    '—'
                  ),
                },
                { label: t('attempts'), value: formatNumber(job.attempt_count ?? 0, locale) },
                { label: t('colCreated'), value: formatDateTime(job.created_at, locale) },
              ]}
            />

            {workflow.data ? (
              <section>
                <h3 className="mb-3 flex flex-wrap items-center gap-2 text-sm font-semibold">
                  {t('pipeline')}
                  {workflow.data.version != null ? (
                    <Badge tone={workflow.data.is_pinned ? 'primary' : 'amber'}>
                      {workflow.data.is_pinned
                        ? t('pipelineVersionPinned', { version: workflow.data.version })
                        : t('pipelineVersionFallback', { version: workflow.data.version })}
                    </Badge>
                  ) : null}
                </h3>
                <WorkflowSteps
                  steps={workflow.data.steps}
                  events={job.events}
                  agentRuns={job.agent_runs}
                  jobStatus={job.status}
                />
              </section>
            ) : null}

            {job.async_task ? (
              <section>
                <h3 className="mb-3 text-sm font-semibold">{t('asyncTask')}</h3>
                <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-amber/40 bg-amber/8 p-3 text-xs">
                  <p className="text-muted">{t('asyncTaskHint')}</p>
                  <DetailList
                    items={[
                      { label: t('asyncTaskNode'), value: asyncTaskStepLabel ?? '—' },
                      {
                        label: t('asyncTaskProvider'),
                        value: job.async_task.provider_label ?? job.async_task.capability_name,
                      },
                      {
                        label: t('asyncTaskExternalId'),
                        value: (
                          <span className="font-mono text-xs">
                            {job.async_task.external_task_id}
                          </span>
                        ),
                      },
                      {
                        label: t('asyncTaskPolls'),
                        value: formatNumber(job.async_task.poll_count, locale),
                      },
                      {
                        label: t('asyncTaskDeadline'),
                        value: formatDateTime(job.async_task.deadline_at, locale),
                      },
                    ]}
                  />
                </div>
              </section>
            ) : null}

            {durationSegments.length > 0 ? (
              <section>
                <h3 className="mb-3 text-sm font-semibold">{t('durationBreakdown')}</h3>
                <DurationBars segments={durationSegments} />
              </section>
            ) : null}

            <section>
              <h3 className="mb-3 text-sm font-semibold">{tAdmin('timeline')}</h3>
              <Timeline entries={timeline} />
            </section>

            <section>
              <h3 className="mb-3 text-sm font-semibold">{t('routing')}</h3>
              <RoutingReplayTable
                candidates={job.routing_trace ?? []}
                chosen={job.provider ?? null}
                reason={job.routing_reason ?? null}
              />
            </section>

            {attempts.length > 0 ? (
              <section>
                <h3 className="mb-3 text-sm font-semibold">{t('attempts')}</h3>
                <ol className="flex flex-col gap-2 text-xs">
                  {attempts.map((attempt) => (
                    <li
                      key={attempt.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-border px-3 py-2"
                    >
                      <span className="font-mono">
                        #{attempt.attempt_number} {attempt.provider}
                      </span>
                      <span className="tabular text-muted">
                        {attempt.status} · {formatNumber(attempt.latency_ms ?? 0, locale)}ms
                        {attempt.cost_credits != null
                          ? ` · ${formatNumber(attempt.cost_credits, locale)} ${t('colCredits')}`
                          : ''}
                        {attempt.error_code ? ` · ${attempt.error_code}` : ''}
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}

            {agentRuns.length > 0 ? (
              <section>
                <h3 className="mb-3 text-sm font-semibold">{t('agentRuns')}</h3>
                <ol className="flex flex-col gap-2 text-xs">
                  {agentRuns.map((run) => (
                    <li
                      key={run.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-border px-3 py-2"
                    >
                      <span className="font-mono">
                        {run.agent_display_name ?? run.agent_name}
                        {run.agent_display_name ? (
                          <span className="ml-1.5 text-muted">
                            ({t('agentProfile', { role: run.agent_name })})
                          </span>
                        ) : null}
                        {run.model ? ` · ${run.model}` : ''}
                        {run.degraded ? (
                          <Badge tone="amber" className="ml-2">
                            {t('degraded')}
                          </Badge>
                        ) : null}
                      </span>
                      <span className="tabular text-muted">
                        {t('promptTokens')} {formatNumber(run.prompt_tokens ?? 0, locale)} ·{' '}
                        {t('completionTokens')} {formatNumber(run.completion_tokens ?? 0, locale)} ·{' '}
                        {formatNumber(run.latency_ms ?? 0, locale)}ms
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}

            <section>
              <h3 className="mb-3 text-sm font-semibold">{t('relatedLogs')}</h3>
              {logRows.length > 0 ? (
                <ol className="flex flex-col gap-2 text-xs">
                  {logRows.map((entry) => (
                    <li
                      key={entry.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-border px-3 py-2"
                    >
                      <span className="flex items-center gap-2">
                        <Badge tone={LOG_SOURCE_TONE[entry.source] ?? 'neutral'}>
                          {entry.source}
                        </Badge>
                        <span className="font-mono">{entry.event}</span>
                        <span className="max-w-[220px] truncate text-muted">{entry.message}</span>
                      </span>
                      <span className="tabular whitespace-nowrap text-muted">
                        {formatDateTime(entry.occurred_at, locale)}
                      </span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-xs text-muted">{t('relatedLogsEmpty')}</p>
              )}
            </section>
          </div>
        ) : null}
      </DetailDrawer>

      <DangerConfirm
        open={danger === 'terminate'}
        onClose={() => setDanger(null)}
        title={t('terminate')}
        description={job?.async_task ? t('terminateAsyncHint') : t('terminateReason')}
        reasonLabel={tAdmin('dangerReason')}
        confirmWord={openId ?? undefined}
        onConfirm={(reason) => act('terminate', reason)}
      />
    </div>
  );
}
