'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { api } from '@/lib/api/client';

const REASONS = [
  'copyright',
  'sexual_content',
  'violence',
  'hate',
  'minor_safety',
  'fraud',
  'other',
] as const;
type Reason = (typeof REASONS)[number];

const DETAIL_MAX_LENGTH = 2000;

/**
 * `subject_type` is fixed to `"work"`: this dialog only ever opens from a work
 * page, and the API's `asset`/`user`/`comment` subjects have no entry point
 * here yet, matching the iOS `ReportSheet`.
 */
export function ReportDialog({
  workId,
  open,
  onClose,
}: {
  workId: string;
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslations('workPage');
  const tActions = useTranslations('actions');

  const [reason, setReason] = useState<Reason>('copyright');
  const [detail, setDetail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const close = () => {
    onClose();
    // Reset after the close animation reads the current state one last time.
    setTimeout(() => {
      setReason('copyright');
      setDetail('');
      setError(null);
      setSubmitted(false);
    }, 0);
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await api.post('/v1/reports', {
        subject_type: 'work',
        subject_id: workId,
        reason,
        detail: detail.trim() || undefined,
      });
      setSubmitted(true);
    } catch {
      setError(t('reportSubmit'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('reportTitle')}
      size="sm"
      footer={
        submitted ? (
          <Button onClick={close}>{tActions('close')}</Button>
        ) : (
          <>
            <Button variant="ghost" onClick={close}>
              {tActions('cancel')}
            </Button>
            <Button onClick={() => void submit()} loading={submitting}>
              {t('reportSubmit')}
            </Button>
          </>
        )
      }
    >
      {submitted ? (
        <p className="text-sm text-success">{t('reportSubmitted')}</p>
      ) : (
        <div className="flex flex-col gap-4">
          {error ? <ErrorNotice title={error} /> : null}
          <Select
            label={t('reportReason')}
            value={reason}
            onChange={(event) => setReason(event.target.value as Reason)}
            options={REASONS.map((value) => ({
              value,
              label: t(`reportReason${toPascalCase(value)}`),
            }))}
          />
          <TextArea
            label={t('reportDetailPlaceholder')}
            placeholder={t('reportDetailPlaceholder')}
            value={detail}
            maxLength={DETAIL_MAX_LENGTH}
            onChange={(event) => setDetail(event.target.value)}
          />
        </div>
      )}
    </Dialog>
  );
}

function toPascalCase(reason: Reason): string {
  return reason
    .split('_')
    .map((part) => part[0]!.toUpperCase() + part.slice(1))
    .join('');
}
