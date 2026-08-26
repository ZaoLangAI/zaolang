'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Select, TextInput } from '@/components/ui/field';
import { useToast } from '@/components/ui/toast';
import * as editorApi from '@/features/editor/api';
import { isApiError } from '@/lib/api/errors';

import { pascalCase } from './format';

const CONTENT_TYPES = ['draft', 'work', 'editor_export'] as const;
const ROLES = ['candidate', 'reference', 'behind_the_scenes', 'final'] as const;

/**
 * "Attach an existing item" — for material that was generated elsewhere and
 * only now being organized into this episode, as opposed to the automatic
 * `linkEpisodeId` deep link a generation studio uses at creation time.
 *
 * There is no endpoint to search drafts/works/editor-exports by title across
 * these three content types together, so this stays a plain paste-the-id
 * form rather than a search picker.
 */
export function AttachContentPicker({
  episodeId,
  onLinked,
}: {
  episodeId: string;
  onLinked: () => void;
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const [contentType, setContentType] = useState<string>('draft');
  const [refId, setRefId] = useState('');
  const [role, setRole] = useState<string>('candidate');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedRefId = refId.trim();

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!trimmedRefId) return;
    setBusy(true);
    setError(null);
    void editorApi
      .createContentLink(episodeId, {
        content_type: contentType,
        content_ref_id: trimmedRefId,
        role,
      })
      .then(() => {
        setRefId('');
        notify(t('attachSuccess'), 'success');
        onLinked();
      })
      .catch((err: unknown) => {
        if (isApiError(err) && err.isForbidden) setError(t('attachForbidden'));
        else if (isApiError(err) && err.isNotFound) setError(t('attachNotFound'));
        else setError(isApiError(err) ? err.message : t('commandFailed'));
      })
      .finally(() => setBusy(false));
  };

  return (
    <form
      className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-dashed border-border p-4"
      onSubmit={submit}
    >
      <div>
        <p className="text-sm font-medium">{t('attachContentTitle')}</p>
        <p className="mt-1 text-xs text-muted">{t('attachContentHint')}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Select
          label={t('contentTypeLabel')}
          value={contentType}
          onChange={(event) => setContentType(event.target.value)}
          options={CONTENT_TYPES.map((value) => ({
            value,
            label: t(`contentType${pascalCase(value)}`),
          }))}
          disabled={busy}
        />
        <TextInput
          label={t('contentRefIdLabel')}
          value={refId}
          onChange={(event) => setRefId(event.target.value)}
          disabled={busy}
        />
        <Select
          label={t('roleFieldLabel')}
          value={role}
          onChange={(event) => setRole(event.target.value)}
          options={ROLES.map((value) => ({ value, label: t(`role${pascalCase(value)}`) }))}
          disabled={busy}
        />
      </div>
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" size="sm" loading={busy} disabled={!trimmedRefId}>
          {t('attachSubmit')}
        </Button>
      </div>
    </form>
  );
}
