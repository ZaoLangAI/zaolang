'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { MultiSelect, TextArea } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { OPERATIONS, OPERATION_LABEL_KEYS, type OperationValue } from '@/lib/admin/operations';
import { adminApi } from '@/lib/api/admin-client';
import type { WorkflowGraphJson, WorkflowTemplateView } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

/**
 * "复制到其他产品类型": publishes the source operation's *currently active*
 * graph, unchanged, to one or more other operations. Deliberately the
 * published graph rather than the canvas draft — copying an unvetted edit
 * everywhere it can reach defeats the point of validating one operation
 * first.
 *
 * Reuses the existing `PUT /v1/admin/workflow-templates/{operation}` per
 * target rather than a new bulk endpoint: each call is its own
 * `AdminDangerous` write (10/300s), so this sends them serially and stops on
 * the first failure — the targets already published stay published, only
 * later ones are skipped, and the dialog reports exactly where it stopped.
 */
export function WorkflowCopyDialog({
  open,
  sourceOperation,
  graph,
  onClose,
}: {
  open: boolean;
  sourceOperation: OperationValue;
  graph: WorkflowGraphJson;
  onClose: () => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const tProviders = useTranslations('adminProviders');
  const [targets, setTargets] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string[]>([]);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open && !wasOpen.current) {
      setTargets([]);
      setReason('');
      setError(null);
      setDone([]);
    }
    wasOpen.current = open;
  }, [open]);

  const options = OPERATIONS.filter((operation) => operation !== sourceOperation).map((operation) => ({
    value: operation,
    label: tProviders(OPERATION_LABEL_KEYS[operation]),
  }));
  const label = (operation: string) => {
    const key = OPERATION_LABEL_KEYS[operation as OperationValue];
    return key ? tProviders(key) : operation;
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    const completed: string[] = [];
    try {
      for (const target of targets) {
        // Keeps whatever name the target already published rather than
        // overwriting it with the source's — `publish()` requires a name,
        // but the point of copying a graph is not to rename someone else's
        // template.
        const active = await adminApi
          .get<WorkflowTemplateView>(`/v1/admin/workflow-templates/${target}`)
          .catch(() => null);
        await adminApi.put(`/v1/admin/workflow-templates/${target}`, {
          name: active?.name ?? t('defaultTemplateName'),
          graph,
          reason,
          confirm: true,
        });
        completed.push(target);
        setDone([...completed]);
      }
    } catch (caught) {
      const failedTarget = targets[completed.length];
      setError(
        caught instanceof ApiError
          ? `${t('copyToOperationsFailed', { operation: label(failedTarget ?? '') })} ${caught.message}`
          : t('copyToOperationsFailed', { operation: label(failedTarget ?? '') }),
      );
    } finally {
      setBusy(false);
    }
  };

  const canRun = targets.length > 0 && reason.trim().length >= 4 && !busy;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('copyToOperations')}
      description={t('copyToOperationsDesc')}
      footer={
        <Button variant="primary" disabled={!canRun} loading={busy} onClick={() => void run()}>
          {t('copyToOperationsRun')}
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <MultiSelect
          label={t('copyToOperationsTargets')}
          value={targets}
          onChange={setTargets}
          options={options}
          disabled={busy}
        />
        <TextArea
          label={tAdmin('dangerReason')}
          hint={tAdmin('dangerReasonHint')}
          value={reason}
          maxLength={500}
          disabled={busy}
          onChange={(event) => setReason(event.target.value)}
        />

        <p className="text-xs text-muted">{t('copyToOperationsQuota')}</p>

        {done.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {done.map((operation) => (
              <Badge key={operation} tone="success">
                {label(operation)}
              </Badge>
            ))}
          </div>
        ) : null}

        {done.length > 0 && !busy && !error ? (
          <p className="text-xs text-success">{t('copyToOperationsDone', { count: done.length })}</p>
        ) : null}

        {error ? <ErrorNotice title={error} /> : null}
      </div>
    </Dialog>
  );
}
