'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { ApiError } from '@/lib/api/errors';

/**
 * Second confirmation for a privileged action, with a mandatory reason.
 *
 * The reason is not decoration: the server rejects these calls without one and
 * writes it to the audit log, so the field is required here for the same reason
 * it is required there. Irreversible actions additionally ask the operator to
 * type a word, which defeats muscle-memory clicking.
 */
export function DangerConfirm({
  open,
  onClose,
  title,
  description,
  reasonLabel,
  confirmWord,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description: string;
  reasonLabel: string;
  /** Set for irreversible actions; the operator must type it exactly. */
  confirmWord?: string;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const t = useTranslations('admin');
  const [reason, setReason] = useState('');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = reason.trim().length >= 4 && (!confirmWord || typed === confirmWord);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      setReason('');
      setTyped('');
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={t('dangerTitle')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('reset')}
          </Button>
          <Button variant="danger" disabled={!ready} loading={busy} onClick={() => void run()}>
            {t('dangerProceed')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">{description}</p>

        <TextArea
          label={reasonLabel}
          hint={t('dangerReasonHint')}
          required
          value={reason}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
        />

        {confirmWord ? (
          <TextInput
            label={t('dangerConfirmWord', { word: confirmWord })}
            required
            value={typed}
            autoComplete="off"
            onChange={(event) => setTyped(event.target.value)}
          />
        ) : null}

        {error ? <ErrorNotice title={error} /> : null}
      </div>
    </Dialog>
  );
}
