'use client';

import { useLocale, useTranslations } from 'next-intl';

import { DataTable, type Column } from '@/components/admin/data-table';
import { FilterBar, Pager } from '@/components/admin/filter-bar';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import type { AgentRun } from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

const AGENTS = ['safety', 'planner', 'quality', 'copy'] as const;

export function AgentRunsTable() {
  const t = useTranslations('adminAgents');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;

  const list = useAdminList<AgentRun>('/v1/admin/agent-runs');

  const columns: Array<Column<AgentRun>> = [
    {
      id: 'agent',
      header: t('colAgent'),
      render: (row) => <span className="text-xs">{row.agent_name}</span>,
    },
    {
      id: 'model',
      header: t('colModel'),
      render: (row) => <span className="font-mono text-xs text-muted">{row.model || '—'}</span>,
    },
    {
      id: 'tokens',
      header: t('colTokens'),
      numeric: true,
      render: (row) =>
        `${formatNumber(row.prompt_tokens ?? 0, locale)} / ${formatNumber(row.completion_tokens ?? 0, locale)}`,
    },
    {
      id: 'latency',
      header: t('colLatency'),
      numeric: true,
      render: (row) => `${formatNumber(row.latency_ms ?? 0, locale)}ms`,
    },
    {
      id: 'degraded',
      header: t('colDegraded'),
      render: (row) =>
        row.degraded ? (
          <Badge tone="amber" className="whitespace-normal">
            {row.error_message ?? t('colDegraded')}
          </Badge>
        ) : (
          <span className="text-xs text-muted">{row.mode}</span>
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

  return (
    <div className="flex flex-col">
      <FilterBar
        filters={[
          {
            id: 'agent_name',
            label: t('colAgent'),
            kind: 'select',
            options: AGENTS.map((value) => ({ value, label: value })),
          },
          {
            id: 'degraded_only',
            label: t('colDegraded'),
            kind: 'select',
            options: [{ value: 'true', label: t('colDegraded') }],
          },
          { id: 'job_id', label: 'job', kind: 'text', placeholder: 'job_…' },
        ]}
        values={list.filters}
        onChange={list.setFilter}
        onReset={list.resetFilters}
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
        />
      </div>

      <Pager
        onPrev={list.prevPage}
        onNext={list.nextPage}
        hasPrev={list.hasPrev}
        hasNext={list.hasNext}
      />
    </div>
  );
}
