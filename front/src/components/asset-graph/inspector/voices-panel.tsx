'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { IconSparkle } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { AssetGraph, GenerationModelOption, VoiceMatchResponse } from '@/lib/api/types';

import { RELATION_COLOR, relationLabelKey, VOICE_RELATIONS } from '../relations';
import type { AssetGraphActions } from '../use-asset-graph';
import { InspectorSection } from './section';
import { VoiceForm, voiceDraft, type VoiceDraft } from './voice-form';

/** The 音色 tab with nothing selected: the card's 音色描述, 「AI 按描述匹配」
 * (a proposal that pre-fills the new-voice form) and the new-voice form. */
export function VoicesPanel({
  graph,
  voiceDescription,
  models,
  busy,
  actions,
  onCreated,
}: {
  graph: AssetGraph;
  voiceDescription: string | null;
  models: GenerationModelOption[];
  busy: boolean;
  actions: AssetGraphActions;
  onCreated: (voiceId: string) => void;
}) {
  const t = useTranslations('assetGraph');
  const [draft, setDraft] = useState<VoiceDraft>(() =>
    voiceDraft(null, (graph.voices ?? []).length ? '' : t('defaultVoiceName')),
  );
  const [formKey, setFormKey] = useState(0);
  const [match, setMatch] = useState<VoiceMatchResponse | null>(null);
  const [matching, setMatching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const count = (graph.voices ?? []).length;
  const atCap = graph.caps.max_voices != null && count >= graph.caps.max_voices;

  const runMatch = async () => {
    setMatching(true);
    setError(null);
    try {
      const proposal = await api.post<VoiceMatchResponse>(`${actions.base}/voices:match`, {});
      setMatch(proposal);
      setDraft((current) => ({
        ...current,
        source: 'preset',
        model: proposal.model,
        voice: proposal.voice,
        speed: proposal.params?.speed ?? null,
        emotion: proposal.params?.emotion ?? '',
      }));
      setFormKey((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('genericError'));
    } finally {
      setMatching(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">{t('voicesTitle')}</h2>
        <p className="mt-1 text-xs text-muted">{t('voicesStats', { count })}</p>
      </div>

      <InspectorSection title={t('voiceDescriptionTitle')}>
        <p className="whitespace-pre-line text-sm text-muted">
          {voiceDescription || t('voiceDescriptionEmpty')}
        </p>
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          icon={<IconSparkle className="size-3.5" />}
          loading={matching}
          disabled={!voiceDescription}
          onClick={() => void runMatch()}
        >
          {t('matchVoice')}
        </Button>
        {match ? (
          <p className="rounded-[var(--radius-sm)] bg-surface-soft p-2.5 text-xs">
            {t('matchResult', { model: match.model_label, voice: match.voice })}
            {match.reason ? ` — ${match.reason}` : ''}
          </p>
        ) : null}
        {error ? <ErrorNotice title={error} /> : null}
      </InspectorSection>

      <InspectorSection title={t('newVoice')}>
        {atCap ? (
          <p className="text-xs text-muted">
            {t('voiceCapReached', { max: graph.caps.max_voices ?? 0 })}
          </p>
        ) : (
          <VoiceForm
            key={formKey}
            initial={draft}
            models={models}
            busy={busy}
            submitLabel={t('createVoice')}
            onSubmit={(body) =>
              void actions.createVoice(body).then((created) => {
                if (created) {
                  setDraft(voiceDraft(null));
                  setMatch(null);
                  setFormKey((value) => value + 1);
                  onCreated(created.id);
                }
              })
            }
          />
        )}
      </InspectorSection>

      <InspectorSection title={t('legendTitle')}>
        <ul className="grid grid-cols-2 gap-1.5 text-xs">
          {VOICE_RELATIONS.map((relation) => (
            <li key={relation} className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-0.5 w-5 rounded"
                style={{ background: RELATION_COLOR[relation] }}
              />
              {t(relationLabelKey(relation))}
            </li>
          ))}
        </ul>
      </InspectorSection>
    </div>
  );
}
