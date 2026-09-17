'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { api } from '@/lib/api/client';

const REASON_MAX_LENGTH = 2000;

/**
 * Owner-only, opened from the hidden-work banner in `WorkInfoPanel`. Shape
 * mirrors `report-dialog.tsx`, minus the reason-code picker — an appeal is a
 * free-text argument, not a categorized complaint.
 */
export function AppealDialog({
  workId,
  open,
  onClose,
  onSubmitted,
}: {
  workId: string;
  open: boolean;
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const t = useTranslations('workPage');
  const tActions = useTranslations('actions');

  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const close = () => {
    onClose();
    setTimeout(() => {
      setReason('');
      setError(null);
      setSubmitted(false);
    }, 0);
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/v1/works/${workId}/appeal`, { reason: reason.trim() });
      setSubmitted(true);
      onSubmitted();
    } catch {
      setError(t('appealSubmit'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('appealTitle')}
      size="sm"
      footer={
        submitted ? (
          <Button onClick={close}>{tActions('close')}</Button>
        ) : (
          <>
            <Button variant="ghost" onClick={close}>
              {tActions('cancel')}
            </Button>
            <Button
              onClick={() => void submit()}
              loading={submitting}
              disabled={reason.trim().length < 4}
            >
              {t('appealSubmit')}
            </Button>
          </>
        )
      }
    >
      {submitted ? (
        <p className="text-sm text-success">{t('appealSubmitted')}</p>
      ) : (
        <div className="flex flex-col gap-4">
          {error ? <ErrorNotice title={error} /> : null}
          <TextArea
            label={t('appealReasonPlaceholder')}
            placeholder={t('appealReasonPlaceholder')}
            value={reason}
            maxLength={REASON_MAX_LENGTH}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
      )}
    </Dialog>
  );
}
