'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { api } from '@/lib/api/client';
import type { CreationSkillCategory, CreationSkillDetail } from '@/lib/api/types';

const CATEGORIES: CreationSkillCategory[] = ['scene', 'lens', 'style', 'other'];

/**
 * Creates a `CreationSkill` (always starts as a private draft).
 *
 * `initialParams` lets the studio's "save as skill" flow prefill the JSON
 * textarea with the current generation parameters; the library tab's own
 * "create skill" tile opens the same dialog with nothing prefilled.
 */
export function CreateSkillDialog({
  open,
  onClose,
  onCreated,
  initialParams,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (skill: CreationSkillDetail) => void;
  initialParams?: Record<string, unknown>;
}) {
  const t = useTranslations('skillLibrary');
  const tActions = useTranslations('actions');

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState<CreationSkillCategory>('scene');
  const [paramsText, setParamsText] = useState(() => JSON.stringify(initialParams ?? {}, null, 2));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setTitle('');
    setDescription('');
    setCategory('scene');
    setParamsText(JSON.stringify(initialParams ?? {}, null, 2));
    setError(null);
  };

  const close = () => {
    onClose();
    reset();
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    let params: Record<string, unknown>;
    try {
      const parsed = JSON.parse(paramsText || '{}');
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error();
      params = parsed as Record<string, unknown>;
    } catch {
      setError(t('paramsInvalid'));
      return;
    }

    setSubmitting(true);
    try {
      const skill = await api.post<CreationSkillDetail>('/v1/skills', {
        title: title.trim(),
        description: description.trim(),
        category,
        params,
      });
      onCreated(skill);
      reset();
    } catch {
      setError(t('createFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title={t('createTitle')} size="md">
      <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
        {error ? <ErrorNotice title={error} /> : null}
        <TextInput
          label={t('titleLabel')}
          required
          autoFocus
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
          options={CATEGORIES.map((value) => ({
            value,
            label: t(
              value === 'scene'
                ? 'categoryScene'
                : value === 'lens'
                  ? 'categoryLens'
                  : value === 'style'
                    ? 'categoryStyle'
                    : 'categoryOther',
            ),
          }))}
        />
        <TextArea
          label={t('paramsLabel')}
          hint={t('paramsHint')}
          className="min-h-40 font-mono text-xs"
          value={paramsText}
          onChange={(event) => setParamsText(event.target.value)}
        />
        <div className="flex items-center justify-end gap-3">
          <Button variant="ghost" onClick={close}>
            {tActions('cancel')}
          </Button>
          <Button type="submit" loading={submitting} disabled={title.trim().length === 0}>
            {t('create')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
