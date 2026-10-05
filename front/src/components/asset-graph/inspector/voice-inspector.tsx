'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import type { CardKind } from '@/components/library/entry-actions';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type {
  AssetGraph,
  CharacterVoice,
  GenerationModelOption,
  VoicePreviewResponse,
} from '@/lib/api/types';

import type { AssetGraphActions } from '../use-asset-graph';
import { VoicePlayButton } from '../voice-play-button';
import { AddRelationForm, RelationsList } from './relations-list';
import { InspectorSection } from './section';
import { VoiceForm, voiceDraft } from './voice-form';

/** A selected voice: its preview, settings, looks, derivation and
 * relations. Mounted per voice (keyed). */
export function VoiceInspector({
  graph,
  kind,
  voice,
  models,
  busy,
  actions,
  onSelectEdge,
  onDeleted,
  onCreated,
}: {
  graph: AssetGraph;
  kind: CardKind;
  voice: CharacterVoice;
  models: GenerationModelOption[];
  busy: boolean;
  actions: AssetGraphActions;
  onSelectEdge: (edgeId: string) => void;
  onDeleted: () => void;
  onCreated: (voiceId: string) => void;
}) {
  const t = useTranslations('assetGraph');
  const tActions = useTranslations('actions');
  const { notify } = useToast();
  const [looks, setLooks] = useState<string[]>(voice.look_ids ?? []);
  const [deriving, setDeriving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [quote, setQuote] = useState<VoicePreviewResponse | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null);
  const previewUrl = `${actions.base}/voices/${voice.id}:preview`;
  const pending = (graph.pending ?? []).some((job) => job.target_voice_id === voice.id);

  useEffect(() => {
    let cancelled = false;
    api
      .post<VoicePreviewResponse>(previewUrl, { dry_run: true })
      .then((response) => {
        if (!cancelled) setQuote(response);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [previewUrl]);

  const generatePreview = async () => {
    setPreviewBusy(true);
    setError(null);
    key.current ??= newIdempotencyKey();
    try {
      await api.post<VoicePreviewResponse>(
        previewUrl,
        { dry_run: false },
        { idempotencyKey: key.current },
      );
      key.current = null;
      notify(t('previewQueued'), 'success');
      await actions.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('genericError'));
    } finally {
      setPreviewBusy(false);
    }
  };

  const looksDirty = [...looks].sort().join(',') !== [...(voice.look_ids ?? [])].sort().join(',');

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h2 className="min-w-0 flex-1 truncate text-base font-semibold">{voice.name}</h2>
        {voice.is_default ? <Badge tone="primary">{t('defaultBadge')}</Badge> : null}
        <Badge>{voice.source === 'clone' ? t('voiceClone') : t('voicePreset')}</Badge>
      </div>

      <InspectorSection title={t('sectionPreview')}>
        <div className="flex flex-wrap items-center gap-2">
          {pending ? (
            <span className="inline-flex items-center gap-1 text-xs text-primary">
              <Spinner className="size-3.5" /> {t('previewGenerating')}
            </span>
          ) : voice.preview?.url ? (
            <VoicePlayButton url={voice.preview.url} />
          ) : (
            <span className="text-xs text-muted">{t('noPreview')}</span>
          )}
          <Button
            size="sm"
            variant="secondary"
            icon={<IconSparkle className="size-3.5" />}
            loading={previewBusy}
            disabled={pending || (quote ? !quote.sufficient : false)}
            onClick={() => void generatePreview()}
          >
            {voice.preview?.url ? t('regeneratePreview') : t('generatePreview')}
          </Button>
        </div>
        <p className="text-xs text-muted">
          {voice.preview_text ? `「${voice.preview_text}」` : t('previewTextDefault')}
          {quote
            ? ` · ${t('quote', { credits: quote.credits, available: quote.available_credits })}`
            : ''}
        </p>
        {error ? <ErrorNotice title={error} /> : null}
      </InspectorSection>

      <InspectorSection title={t('sectionVoiceLooks')}>
        {(graph.variants ?? []).length ? (
          <ul className="flex flex-col gap-1.5">
            {(graph.variants ?? []).map((look) => (
              <li key={look.id}>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={looks.includes(look.id)}
                    onChange={(event) =>
                      setLooks((current) =>
                        event.target.checked
                          ? [...current, look.id]
                          : current.filter((id) => id !== look.id),
                      )
                    }
                    className="size-4 accent-[var(--primary)]"
                  />
                  {look.name}
                  {look.voice_id && look.voice_id !== voice.id ? (
                    <span className="text-xs text-muted">{t('lookHasOtherVoice')}</span>
                  ) : null}
                </label>
              </li>
            ))}
          </ul>
        ) : null}
        <Button
          size="sm"
          className="self-start"
          disabled={!looksDirty}
          loading={busy}
          onClick={() => void actions.updateVoice(voice.id, { look_ids: looks })}
        >
          {t('saveVoiceLooks')}
        </Button>
      </InspectorSection>

      <InspectorSection title={t('sectionVoiceSettings')}>
        <VoiceForm
          initial={voiceDraft(voice)}
          models={models}
          busy={busy}
          submitLabel={t('saveVoice')}
          onSubmit={(body) => void actions.updateVoice(voice.id, body)}
        />
      </InspectorSection>

      <InspectorSection title={t('sectionVoiceDerive')}>
        {deriving ? (
          <VoiceForm
            initial={voiceDraft(voice, '')}
            models={models}
            busy={busy}
            submitLabel={t('deriveVoiceSubmit')}
            onSubmit={(body) =>
              void actions.createVoice({ ...body, derived_from: voice.id }).then((created) => {
                if (created) {
                  setDeriving(false);
                  onCreated(created.id);
                }
              })
            }
          />
        ) : (
          <>
            <p className="text-xs text-muted">{t('deriveVoiceHint')}</p>
            <Button
              size="sm"
              variant="secondary"
              className="self-start"
              onClick={() => setDeriving(true)}
            >
              {t('deriveVoice')}
            </Button>
          </>
        )}
      </InspectorSection>

      <InspectorSection title={t('sectionRelations')}>
        <RelationsList graph={graph} level="voice" nodeId={voice.id} onSelectEdge={onSelectEdge} />
        <AddRelationForm
          graph={graph}
          kind={kind}
          level="voice"
          nodeId={voice.id}
          busy={busy}
          onCreate={actions.createEdge}
        />
      </InspectorSection>

      <InspectorSection title={t('sectionManage')}>
        <div className="flex flex-wrap gap-2">
          {!voice.is_default ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void actions.updateVoice(voice.id, { make_default: true })}
            >
              {t('makeDefaultVoice')}
            </Button>
          ) : null}
          <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>
            {t('deleteVoice')}
          </Button>
        </div>
      </InspectorSection>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t('deleteVoiceTitle', { name: voice.name })}
        description={t('deleteVoiceHint')}
        confirmLabel={tActions('delete')}
        cancelLabel={tActions('cancel')}
        busy={busy}
        onConfirm={() =>
          void actions.deleteVoice(voice.id).then((done) => {
            setConfirmDelete(false);
            if (done) onDeleted();
          })
        }
      />
    </div>
  );
}
