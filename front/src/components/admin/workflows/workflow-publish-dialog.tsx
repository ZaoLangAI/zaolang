'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { adminApi } from '@/lib/api/admin-client';
import type { WorkflowGraphJson, WorkflowTemplateValidateResponse } from '@/lib/api/admin-types';
import { ApiError } from '@/lib/api/errors';

/**
 * Publishing writes a new version and makes it active for every job
 * submitted from now on — same ceremony as `AgentSkillEditorDialog`'s
 * publish: a mandatory reason plus an explicit confirm flag the server
 * checks again itself.
 */
export function WorkflowPublishDialog({
  open,
  operation,
  graph,
  defaultName,
  onClose,
  onPublished,
}: {
  open: boolean;
  operation: string;
  graph: WorkflowGraphJson;
  defaultName: string;
  onClose: () => void;
  onPublished: () => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const [name, setName] = useState(defaultName);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  const validate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await adminApi.post<WorkflowTemplateValidateResponse>(
        '/v1/admin/workflow-templates/validate',
        { graph },
      );
      setValidationErrors(result.errors ?? []);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      await adminApi.put(`/v1/admin/workflow-templates/${operation}`, {
        name,
        graph,
        reason,
        confirm: true,
      });
      setReason('');
      onPublished();
    } catch (caught) {
      if (caught instanceof ApiError && Array.isArray(caught.details.errors)) {
        setValidationErrors(caught.details.errors as string[]);
      }
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('publish')}
      description={t('publishDesc')}
      footer={
        <>
          <Button variant="ghost" onClick={() => void validate()} loading={busy}>
            {t('validateGraph')}
          </Button>
          <Button
            variant="primary"
            disabled={name.trim().length === 0 || reason.trim().length < 4}
            loading={busy}
            onClick={() => void publish()}
          >
            {t('publishAndActivate')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <TextInput
          label={t('templateName')}
          value={name}
          maxLength={80}
          onChange={(event) => setName(event.target.value)}
        />
        <TextArea
          label={tAdmin('dangerReason')}
          hint={tAdmin('dangerReasonHint')}
          value={reason}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
        />

        {validationErrors.length > 0 ? (
          <div className="rounded-[var(--radius-sm)] border border-danger/40 bg-danger/8 p-3">
            <p className="text-sm font-medium text-danger">{t('validationFailed')}</p>
            <ul className="mt-1.5 list-disc pl-4 text-xs text-muted">
              {validationErrors.map((message, index) => (
                <li key={index}>{message}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {error ? <ErrorNotice title={error} /> : null}
      </div>
    </Dialog>
  );
}
