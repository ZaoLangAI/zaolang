'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  SandboxRunInspector,
  type SandboxTraceStep,
} from '@/components/admin/workflows/sandbox-run-inspector';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { IconClose } from '@/components/ui/icons';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { Locale } from '@/i18n/routing';
import { useAdminList } from '@/lib/admin/use-admin-list';
import type { WorkflowSandboxRunSummary } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';
import { useAdminJobStream } from '@/lib/use-admin-job-stream';

/**
 * Non-modal right-hand drawer of past sandbox try-its. Clicking a row opens
 * a dialog that replays node progress via `GET /v1/admin/jobs/{id}`.
 */
export function WorkflowSandboxHistoryPanel({
  operation,
  onClose,
  onTrace,
}: {
  operation: string;
  onClose: () => void;
  onTrace?: (trace: SandboxTraceStep[] | null) => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const tJob = useTranslations('job');
  const locale = useLocale() as Locale;
  const list = useAdminList<WorkflowSandboxRunSummary>(
    `/v1/admin/workflow-templates/${operation}/sandbox-runs`,
    { pageSize: 20 },
  );
  const [selected, setSelected] = useState<WorkflowSandboxRunSummary | null>(null);
  const stream = useAdminJobStream(selected?.job_id ?? null);

  const closePanel = () => {
    onTrace?.(null);
    setSelected(null);
    onClose();
  };

  const closeDetail = () => {
    setSelected(null);
  };

  return (
    <>
      <aside
        role="complementary"
        aria-label={t('sandboxHistory')}
        className="flex h-[70vh] min-h-[520px] w-[22rem] shrink-0 flex-col overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface"
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">{t('sandboxHistory')}</h2>
            <p className="mt-0.5 text-xs text-muted">{t('sandboxHistoryDesc')}</p>
          </div>
          <button
            type="button"
            onClick={closePanel}
            aria-label={tAdmin('closeDetail')}
            className="grid size-8 shrink-0 place-items-center rounded-[var(--radius-sm)] text-muted hover:bg-surface-soft hover:text-text"
          >
            <IconClose className="size-4" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-3 py-3">
          {list.failed ? <ErrorNotice title={tAdmin('loadFailed')} /> : null}
          {list.loading ? (
            <div className="flex flex-1 items-center justify-center">
              <Spinner />
            </div>
          ) : list.rows.length === 0 ? (
            <p className="px-1 py-6 text-center text-xs text-muted">
              {t('sandboxHistoryEmpty')}
              <span className="mt-1 block">{t('sandboxHistoryEmptyDesc')}</span>
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {list.rows.map((row) => {
                const active = row.job_id === selected?.job_id;
                const who = row.user_display_name ?? row.user_handle ?? row.job_id;
                return (
                  <li key={row.job_id}>
                    <button
                      type="button"
                      title={row.job_id}
                      onClick={() => setSelected(row)}
                      className={`flex w-full flex-col gap-1.5 rounded-[var(--radius-sm)] border px-3 py-2.5 text-left text-sm ${
                        active
                          ? 'border-accent bg-accent/10'
                          : 'border-border hover:border-accent/40'
                      }`}
                    >
                      <span className="line-clamp-2 font-medium">
                        {row.prompt_excerpt || t('sandboxHistoryNoPrompt')}
                      </span>
                      <span className="flex flex-wrap items-center gap-1.5">
                        <Badge
                          tone={
                            row.status === 'succeeded'
                              ? 'success'
                              : row.status === 'awaiting_input'
                                ? 'amber'
                                : row.status === 'failed' ||
                                    row.status === 'cancelled' ||
                                    row.status === 'expired'
                                  ? 'danger'
                                  : 'primary'
                          }
                        >
                          {tJob(row.status)}
                        </Badge>
                        <Badge tone={row.used_draft ? 'amber' : 'neutral'}>
                          {row.used_draft
                            ? t('sandboxHistoryDraft')
                            : t('sandboxHistoryPublished')}
                        </Badge>
                      </span>
                      <span className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                        <span title={row.job_id}>{who}</span>
                        <span className="tabular">{formatDateTime(row.created_at, locale)}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {list.hasPrev || list.hasNext ? (
          <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
            <Button size="sm" variant="ghost" disabled={!list.hasPrev} onClick={list.prevPage}>
              {tAdmin('prevPage')}
            </Button>
            <Button size="sm" variant="ghost" disabled={!list.hasNext} onClick={list.nextPage}>
              {tAdmin('nextPage')}
            </Button>
          </div>
        ) : null}
      </aside>

      <Dialog
        open={selected !== null}
        onClose={closeDetail}
        size="xl"
        title={t('sandboxHistoryDetail')}
        description={
          selected
            ? `${selected.user_display_name ?? selected.user_handle ?? ''} · ${selected.quality_tier}`
            : undefined
        }
      >
        {selected ? (
          <SandboxRunInspector
            jobId={selected.job_id}
            events={stream.events}
            detail={stream.detail}
            reconnecting={stream.reconnecting}
            idleLabel={t('sandboxHistoryIdle')}
            onTrace={onTrace}
          />
        ) : null}
      </Dialog>
    </>
  );
}
