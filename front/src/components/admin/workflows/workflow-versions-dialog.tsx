'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { DangerConfirm } from '@/components/admin/danger-confirm';
import { JsonDiff } from '@/components/admin/json-diff';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { adminApi } from '@/lib/api/admin-client';
import type { WorkflowGraphJson, WorkflowTemplateView } from '@/lib/api/admin-types';
import { formatDateTime } from '@/lib/format';

/**
 * Version history for one operation's graph, with rollback.
 *
 * Rollback re-publishes an earlier version's `graph_json` as the newest
 * version (`workflow_templates.service.activate_version`) — never an
 * in-place edit — so the mistake and the correction both stay in history,
 * same as `AgentSkillEditorDialog`'s "roll back to this version".
 */
export function WorkflowVersionsDialog({
  open,
  operation,
  currentGraph,
  versions,
  editable,
  onClose,
  onRolledBack,
}: {
  open: boolean;
  operation: string;
  currentGraph: WorkflowGraphJson;
  versions: WorkflowTemplateView[];
  editable: boolean;
  onClose: () => void;
  onRolledBack: () => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const locale = useLocale() as Locale;
  const [comparing, setComparing] = useState<WorkflowTemplateView | null>(null);
  const [rollingBackTo, setRollingBackTo] = useState<WorkflowTemplateView | null>(null);

  const rollback = async (reason: string) => {
    if (!rollingBackTo) return;
    await adminApi.post(
      `/v1/admin/workflow-templates/${operation}/activate/${rollingBackTo.id}`,
      { reason, confirm: true },
    );
    setRollingBackTo(null);
    onRolledBack();
  };

  return (
    <Dialog open={open} onClose={onClose} size="lg" title={t('versionHistory')}>
      {versions.length === 0 ? (
        <p className="text-xs text-muted">{t('noVersionsYet')}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {versions.map((version) => (
            <li
              key={version.id}
              className="rounded-[var(--radius-sm)] border border-border px-3 py-2.5 text-sm"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">v{version.version}</span>
                  <span className="font-medium">{version.name}</span>
                  {version.is_active ? <Badge tone="success">{t('active')}</Badge> : null}
                </span>
                <span className="flex items-center gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setComparing(version)}>
                    {t('compareToCurrent')}
                  </Button>
                  {editable && !version.is_active ? (
                    <Button size="sm" variant="secondary" onClick={() => setRollingBackTo(version)}>
                      {t('rollbackToVersion')}
                    </Button>
                  ) : null}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted">
                {formatDateTime(version.created_at, locale)}
                {version.reason ? ` · ${version.reason}` : ''}
              </p>

              {comparing?.id === version.id ? (
                <div className="mt-2.5 border-t border-border pt-2.5">
                  <p className="mb-1.5 text-xs font-semibold text-muted">{t('diffAgainstCurrent')}</p>
                  <JsonDiff before={version.graph} after={currentGraph} />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <DangerConfirm
        open={rollingBackTo !== null}
        onClose={() => setRollingBackTo(null)}
        title={t('rollbackToVersion')}
        description={t('rollbackDesc', { version: rollingBackTo?.version ?? 0 })}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={rollback}
      />
    </Dialog>
  );
}
