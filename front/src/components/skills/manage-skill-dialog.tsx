'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import type { CreationSkillCategory, CreationSkillDetail, CreationSkillSummary } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

const CATEGORIES: CreationSkillCategory[] = ['scene', 'lens', 'style', 'other'];
const CATEGORY_LABEL_KEY: Record<
  CreationSkillCategory,
  'categoryScene' | 'categoryLens' | 'categoryStyle' | 'categoryOther'
> = {
  scene: 'categoryScene',
  lens: 'categoryLens',
  style: 'categoryStyle',
  other: 'categoryOther',
};

/**
 * Owner-only edit surface for one `CreationSkill`: rename/re-describe/re-file
 * it, then share it (submit for review) or withdraw an already-shared one.
 *
 * Params are edited once, at creation — this dialog never touches
 * `params_json`, so a skill already in use elsewhere never silently changes
 * shape underneath whoever applied it.
 */
export function ManageSkillDialog({
  skill,
  onClose,
  onChanged,
}: {
  skill: CreationSkillSummary;
  onClose: () => void;
  onChanged: () => void;
}) {
  const t = useTranslations('skillLibrary');
  const tActions = useTranslations('actions');
  const { notify } = useToast();

  // The update endpoint takes the full record, not a partial patch — the
  // detail fetch is what keeps `params_json`/`cover_asset_id` intact since
  // this dialog never exposes controls for either.
  const detail = useResource<CreationSkillDetail>(`/v1/skills/${skill.id}`);

  const [title, setTitle] = useState(skill.title);
  const [description, setDescription] = useState(skill.description);
  const [category, setCategory] = useState<CreationSkillCategory>(skill.category);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!detail.data) return;
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/v1/skills/${skill.id}`, {
        title: title.trim(),
        description: description.trim(),
        category,
        params: detail.data.params ?? {},
        cover_asset_id: detail.data.cover_asset_id,
      });
      notify(t('saveChanges'), 'success');
      onChanged();
    } catch {
      setError(t('saveFailed'));
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/v1/skills/${skill.id}/publish`);
      notify(t('publishDone'), 'success');
      onChanged();
    } catch {
      setError(t('saveFailed'));
    } finally {
      setBusy(false);
    }
  };

  const withdraw = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/v1/skills/${skill.id}/withdraw`);
      notify(t('withdrawDone'), 'success');
      onChanged();
    } catch {
      setError(t('saveFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={t('manageTitle')} size="md">
      <div className="flex flex-col gap-4">
        {error ? <ErrorNotice title={error} /> : null}

        {skill.status === 'rejected' && detail.data?.reject_reason ? (
          <div className="rounded-[var(--radius-sm)] border border-danger/30 bg-danger/8 px-3 py-2.5 text-xs text-danger">
            <p className="font-medium">{t('rejectReason')}</p>
            <p className="mt-0.5">{detail.data.reject_reason}</p>
          </div>
        ) : null}

        <TextInput
          label={t('titleLabel')}
          required
          maxLength={80}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <TextArea
          label={t('descriptionLabel')}
          maxLength={300}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <Select
          label={t('categoryLabel')}
          value={category}
          onChange={(event) => setCategory(event.target.value as CreationSkillCategory)}
          options={CATEGORIES.map((value) => ({ value, label: t(CATEGORY_LABEL_KEY[value]) }))}
        />

        <div className="flex items-center justify-between border-t border-border pt-4">
          <div className="flex items-center gap-2">
            {skill.status === 'draft' || skill.status === 'rejected' ? (
              <Button size="sm" variant="secondary" loading={busy} onClick={() => void publish()}>
                {t('publish')}
              </Button>
            ) : null}
            {skill.status === 'pending_review' || skill.status === 'published' ? (
              <Button size="sm" variant="ghost" loading={busy} onClick={() => void withdraw()}>
                {t('withdraw')}
              </Button>
            ) : null}
          </div>
          <div className="flex items-center gap-3">
            <Button variant="ghost" onClick={onClose}>
              {tActions('cancel')}
            </Button>
            <Button
              loading={busy}
              disabled={title.trim().length === 0 || !detail.data}
              onClick={() => void save()}
            >
              {tActions('save')}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}