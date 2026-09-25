'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextInput } from '@/components/ui/field';
import { cn } from '@/lib/cn';

import type { AspectRatio } from './types';

const ASPECTS: AspectRatio[] = ['9:16', '16:9', '1:1'];
const MAX_TARGET_SECONDS = 1800;

/**
 * Target episode runtime and delivery aspect. Saving re-fits segment
 * durations deterministically on the server — no model call — so it is safe
 * to nudge repeatedly while watching the result.
 */
export function BlockingSettingsDialog({
  open,
  onClose,
  targetSeconds,
  defaultTargetSeconds,
  aspect,
  saving,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  targetSeconds: number | null;
  defaultTargetSeconds: number;
  aspect: AspectRatio;
  saving: boolean;
  onSave: (input: { targetSeconds: number | null; aspect: AspectRatio }) => void;
}) {
  const t = useTranslations('blockingStudio');
  const [draftTarget, setDraftTarget] = useState(targetSeconds ? String(targetSeconds) : '');
  const [draftAspect, setDraftAspect] = useState<AspectRatio>(aspect);

  const parsed = draftTarget.trim() === '' ? null : Number(draftTarget);
  const invalid =
    parsed !== null && (!Number.isInteger(parsed) || parsed < 1 || parsed > MAX_TARGET_SECONDS);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('settings')}
      description={t('settingsHint')}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            {t('cancel')}
          </Button>
          <Button
            loading={saving}
            disabled={invalid || saving}
            onClick={() => onSave({ targetSeconds: parsed, aspect: draftAspect })}
          >
            {t('save')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <TextInput
          label={t('targetDuration')}
          hint={t('targetDurationHint', { seconds: defaultTargetSeconds })}
          error={invalid ? t('targetDurationInvalid', { max: MAX_TARGET_SECONDS }) : undefined}
          inputMode="numeric"
          placeholder={String(defaultTargetSeconds)}
          value={draftTarget}
          onChange={(event) => setDraftTarget(event.target.value.replace(/[^0-9]/g, ''))}
        />
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-sm font-medium text-text">{t('aspectRatio')}</legend>
          <div className="flex gap-2">
            {ASPECTS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={draftAspect === option}
                onClick={() => setDraftAspect(option)}
                className={cn(
                  'h-11 flex-1 rounded-[var(--radius-sm)] border text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-focus',
                  draftAspect === option
                    ? 'border-primary/50 bg-primary/10 text-text'
                    : 'border-border bg-surface-soft text-muted hover:text-text',
                )}
              >
                {option}
              </button>
            ))}
          </div>
        </fieldset>
      </div>
    </Dialog>
  );
}
