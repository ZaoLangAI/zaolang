'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select, TextArea } from '@/components/ui/field';
import { IconSparkle } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { CharacterDescribeResponse, CharacterScriptLink } from '@/lib/api/types';

export interface CharacterProfileText {
  description: string;
  voiceDescription: string;
}

type DescribeField = 'description' | 'voice_description';

/**
 * 「根据剧本 AI 生成」: drafts a character's description and voice
 * description from the scripts that link it (`POST /v1/characters/{id}/describe`).
 * The draft is shown next to the current text and stays editable; nothing
 * reaches the card until `onApply` — the edit form fills its fields, the
 * script side PATCHes the card.
 */
export function CharacterDescribeDialog({
  open,
  onClose,
  characterId,
  current,
  episodeId,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  characterId: string;
  current: CharacterProfileText;
  /** Opened from one script: draft from it alone by default. */
  episodeId?: string;
  onApply: (next: Partial<CharacterProfileText>) => void | Promise<void>;
}) {
  const t = useTranslations('characters');
  const tActions = useTranslations('actions');
  const [links, setLinks] = useState<CharacterScriptLink[] | null>(null);
  const [source, setSource] = useState(episodeId ?? '');
  const [fields, setFields] = useState<Record<DescribeField, boolean>>({
    description: true,
    voice_description: true,
  });
  const [draft, setDraft] = useState<CharacterProfileText | null>(null);
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Mounted per opening (callers render it conditionally), so state starts
  // fresh each time; this only loads the scripts to draft from.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .get<CharacterScriptLink[]>(`/v1/characters/${characterId}/script-links`)
      .then((rows) => {
        if (!cancelled) setLinks(rows);
      })
      .catch(() => {
        if (!cancelled) setLinks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, characterId]);

  const wanted = (Object.keys(fields) as DescribeField[]).filter((field) => fields[field]);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = await api.post<CharacterDescribeResponse>(
        `/v1/characters/${characterId}/describe`,
        { episode_id: source || null, fields: wanted },
      );
      setDraft({
        description: body.description ?? '',
        voiceDescription: body.voice_description ?? '',
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('describeFailed'));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!draft) return;
    setApplying(true);
    setError(null);
    try {
      await onApply({
        ...(fields.description && draft.description.trim()
          ? { description: draft.description.trim() }
          : {}),
        ...(fields.voice_description && draft.voiceDescription.trim()
          ? { voiceDescription: draft.voiceDescription.trim() }
          : {}),
      });
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('describeFailed'));
    } finally {
      setApplying(false);
    }
  };

  const fieldRow = (
    field: DescribeField,
    label: string,
    currentText: string,
    key: keyof CharacterProfileText,
    maxLength: number,
  ) =>
    fields[field] ? (
      <section className="grid gap-3 md:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-muted">{t('describeCurrent', { field: label })}</p>
          <p className="min-h-20 whitespace-pre-line rounded-[var(--radius-sm)] border border-border bg-surface-soft p-2.5 text-sm text-muted">
            {currentText || t('describeEmpty')}
          </p>
        </div>
        {draft ? (
          <TextArea
            label={t('describeDraft', { field: label })}
            value={draft[key]}
            maxLength={maxLength}
            onChange={(event) =>
              setDraft((value) => (value ? { ...value, [key]: event.target.value } : value))
            }
          />
        ) : (
          <div className="hidden md:block" />
        )}
      </section>
    ) : null;

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!busy && !applying) onClose();
      }}
      title={t('describeTitle')}
      description={t('describeHint')}
      size="xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy || applying}>
            {tActions('cancel')}
          </Button>
          <Button
            variant={draft ? 'secondary' : 'primary'}
            icon={<IconSparkle className="size-4" />}
            loading={busy}
            disabled={!links?.length || wanted.length === 0 || applying}
            onClick={() => void generate()}
          >
            {draft ? t('describeRegenerate') : t('describeGenerate')}
          </Button>
          {draft ? (
            <Button loading={applying} disabled={busy} onClick={() => void apply()}>
              {t('describeApply')}
            </Button>
          ) : null}
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {links === null ? (
          <Spinner className="size-4" />
        ) : links.length === 0 ? (
          <p className="text-sm text-muted">{t('describeNoLinks')}</p>
        ) : (
          <div className="flex flex-wrap items-end gap-4">
            <div className="min-w-56 flex-1">
              <Select
                label={t('describeSource')}
                value={source}
                onChange={(event) => setSource(event.target.value)}
                options={[
                  { value: '', label: t('describeAllScripts', { count: links.length }) },
                  ...links.map((link) => ({
                    value: link.episode_id,
                    label: `${link.series_title} · ${link.episode_title}（${link.character_name}）`,
                  })),
                ]}
              />
            </div>
            <fieldset className="flex gap-4 pb-2">
              <legend className="sr-only">{t('describeFields')}</legend>
              {(
                [
                  ['description', t('descriptionLabel')],
                  ['voice_description', t('voiceLabel')],
                ] as const
              ).map(([field, label]) => (
                <label key={field} className="flex cursor-pointer items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={fields[field]}
                    onChange={(event) =>
                      setFields((value) => ({ ...value, [field]: event.target.checked }))
                    }
                    className="size-4 accent-[var(--primary)]"
                  />
                  {label}
                </label>
              ))}
            </fieldset>
          </div>
        )}
        {error ? <ErrorNotice title={error} /> : null}
        {fieldRow('description', t('descriptionLabel'), current.description, 'description', 2000)}
        {fieldRow(
          'voice_description',
          t('voiceLabel'),
          current.voiceDescription,
          'voiceDescription',
          500,
        )}
      </div>
    </Dialog>
  );
}
