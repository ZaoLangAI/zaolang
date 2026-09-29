'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import type { CreationSkillDetail } from '@/lib/api/types';

/**
 * "另存为可分享技能" for a succeeded cover-kind job — shared by the
 * standalone job page and `InlineImageResult`.
 */
export function SaveCoverAsSkillDialog({
  open,
  onClose,
  outputAssetId,
}: {
  open: boolean;
  onClose: () => void;
  outputAssetId: string | null | undefined;
}) {
  const t = useTranslations('jobPage');
  const tActions = useTranslations('actions');
  const tSkills = useTranslations('skillLibrary');
  const { notify } = useToast();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [credits, setCredits] = useState(0);
  const [busy, setBusy] = useState(false);

  // Reset on each open, adjusted during render rather than in an effect
  // (same pattern as `command-palette.tsx`).
  const [wasOpen, setWasOpen] = useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setTitle('');
      setDescription('');
      setCredits(0);
    }
  }

  const save = async () => {
    if (!outputAssetId) return;
    const trimmed = title.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      await api.post<CreationSkillDetail>('/v1/skills', {
        title: trimmed,
        description: description.trim(),
        category: 'cover_asset',
        cover_asset_id: outputAssetId,
        params: { cover_asset_id: outputAssetId },
        access_credits: credits,
      });
      notify(t('saveCoverSkillDone'), 'success');
      setTitle('');
      setDescription('');
      setCredits(0);
      onClose();
    } catch {
      notify(t('saveCoverSkillFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!busy) onClose();
      }}
      title={t('saveCoverSkillTitle')}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {tActions('cancel')}
          </Button>
          <Button loading={busy} disabled={title.trim().length === 0} onClick={() => void save()}>
            {tActions('save')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-xs text-muted">{t('saveCoverSkillHint')}</p>
        <TextInput
          label={t('saveCoverSkillTitleLabel')}
          required
          maxLength={80}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <TextArea
          label={t('saveCoverSkillDescriptionLabel')}
          maxLength={300}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <AccessPriceField
          value={credits}
          onChange={setCredits}
          label={tSkills('priceLabel')}
          hint={tSkills('priceHint')}
        />
      </div>
    </Dialog>
  );
}
