'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

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
  assetKind,
  graph,
  defaultName,
  onClose,
  onValidated,
  onPublished,
}: {
  open: boolean;
  operation: string;
  /** `null` publishes the generic (asset_kind-less) template; a value scopes
   * this publish to that one image-asset purpose (see `operationHasAssetKinds`). */
  assetKind?: string | null;
  graph: WorkflowGraphJson;
  defaultName: string;
  onClose: () => void;
  /** Lifted so the canvas can outline the nodes these messages are about,
   * even after this dialog closes. */
  onValidated?: (errors: string[]) => void;
  onPublished: () => void;
}) {
  const t = useTranslations('adminWorkflows');
  const tAdmin = useTranslations('admin');
  const [name, setName] = useState(defaultName);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [validationWarnings, setValidationWarnings] = useState<string[]>([]);
  const wasOpen = useRef(false);

  const validate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await adminApi.post<WorkflowTemplateValidateResponse>(
        '/v1/admin/workflow-templates/validate',
        { graph, operation },
      );
      const errors = result.errors ?? [];
      setValidationErrors(errors);
      setValidationWarnings(result.warnings ?? []);
      onValidated?.(errors);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  // `defaultName` only carries the real template name once the operation
  // tab's own fetch resolves — on the *first* render it is still the
  // "default generation flow" placeholder. Re-seeding `name` only on the
  // false→true transition (not on every `defaultName` change while open)
  // is what fixed the previous `useState(defaultName)`: that only ever ran
  // once total, so the real name landing after this dialog had already
  // mounted silently reset whatever the operator had typed.
  useEffect(() => {
    if (open && !wasOpen.current) {
      setName(defaultName);
      setReason('');
      setError(null);
      void validate();
    }
    wasOpen.current = open;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultName]);

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      await adminApi.put(`/v1/admin/workflow-templates/${operation}`, {
        name,
        graph,
        reason,
        confirm: true,
        asset_kind: assetKind ?? null,
      });
      setReason('');
      onValidated?.([]);
      onPublished();
    } catch (caught) {
      if (caught instanceof ApiError && Array.isArray(caught.details.errors)) {
        const errors = caught.details.errors as string[];
        setValidationErrors(errors);
        onValidated?.(errors);
      }
      setError(caught instanceof ApiError ? caught.message : tAdmin('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const canPublish =
    name.trim().length > 0 && reason.trim().length >= 4 && validationErrors.length === 0;

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
            disabled={!canPublish}
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

        {/* Advisory only — the server publishes regardless. Shown so a
            capability mismatch is a decision rather than a surprise. */}
        {validationWarnings.length > 0 ? (
          <div className="rounded-[var(--radius-sm)] border border-amber/40 bg-amber/8 p-3">
            <p className="text-sm font-medium text-amber">{t('validationWarnings')}</p>
            <ul className="mt-1.5 list-disc pl-4 text-xs text-muted">
              {validationWarnings.map((message, index) => (
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
