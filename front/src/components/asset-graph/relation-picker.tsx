'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';

import type { CardKind } from '@/components/library/entry-actions';

import { RelationFields, relationDraftValid, type RelationDraft } from './relation-fields';

/**
 * Opened by a drag between two handles: pick what the new relation means.
 * Mounted per connection (callers render it conditionally), so it always
 * starts empty.
 */
export function RelationPickerDialog({
  kind,
  sourceName,
  targetName,
  busy,
  onCancel,
  onConfirm,
}: {
  kind: CardKind;
  sourceName: string;
  targetName: string;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: (draft: RelationDraft) => void;
}) {
  const t = useTranslations('assetGraph');
  const tActions = useTranslations('actions');
  const [draft, setDraft] = useState<RelationDraft>({ relations: [], label: '' });
  return (
    <Dialog
      open
      onClose={() => {
        if (!busy) onCancel();
      }}
      title={t('connectTitle')}
      description={t('connectHint', { source: sourceName, target: targetName })}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {tActions('cancel')}
          </Button>
          <Button
            loading={busy}
            disabled={!relationDraftValid(draft)}
            onClick={() => onConfirm(draft)}
          >
            {t('connectConfirm')}
          </Button>
        </>
      }
    >
      <RelationFields kind={kind} value={draft} onChange={setDraft} />
    </Dialog>
  );
}
