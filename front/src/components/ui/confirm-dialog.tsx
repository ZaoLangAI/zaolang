'use client';

import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';

/**
 * Consumer confirmation for a destructive action.
 *
 * Deliberately not admin `DangerConfirm`: that component requires a written
 * reason for the audit log. Here the server does not ask for one.
 */
export function ConfirmDialog({
  open,
  onClose,
  title,
  description,
  children,
  confirmLabel,
  cancelLabel,
  busy,
  error,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant="danger" loading={busy} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {error ? <ErrorNotice title={error} /> : null}
      {children}
    </Dialog>
  );
}
