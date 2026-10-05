'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Select } from '@/components/ui/field';
import { Spinner } from '@/components/ui/spinner';
import { api } from '@/lib/api/client';
import type { CharacterVoice } from '@/lib/api/types';

import { defaultSpeakerVoice, type SpeakerLink } from './voice-plan';

const NO_VOICES: Record<string, CharacterVoice[]> = {};

/** Loads the voices of every card the speakers link to (owner-only). A
 * card that fails to load just has no voices — its speaker uses the
 * global voice. */
export function useSpeakerCardVoices(speakers: SpeakerLink[]): {
  voicesByCard: Record<string, CharacterVoice[]>;
  loading: boolean;
} {
  const cardIds = [...new Set(speakers.map((s) => s.cardId).filter(Boolean) as string[])].sort();
  const key = cardIds.join(',');
  const [loaded, setLoaded] = useState<{ key: string; voices: Record<string, CharacterVoice[]> }>({
    key: '',
    voices: {},
  });

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    void Promise.all(
      key.split(',').map((id) =>
        api
          .get<CharacterVoice[]>(`/v1/characters/${id}/voices`)
          .then((voices) => [id, voices] as const)
          .catch(() => [id, [] as CharacterVoice[]] as const),
      ),
    ).then((pairs) => {
      if (!cancelled) setLoaded({ key, voices: Object.fromEntries(pairs) });
    });
    return () => {
      cancelled = true;
    };
  }, [key]);

  // Stable identities while nothing changed — callers memoise on them.
  return {
    voicesByCard: key && loaded.key === key ? loaded.voices : NO_VOICES,
    loading: Boolean(key) && loaded.key !== key,
  };
}

/**
 * Who speaks with which voice in a dubbing batch: each speaker's character
 * voice (the one bound to the script's look, else the card's default),
 * overridable per speaker; speakers without one use the global voice.
 */
export function SpeakerVoiceTable({
  speakers,
  voicesByCard,
  loading,
  overrides,
  onOverride,
}: {
  speakers: SpeakerLink[];
  voicesByCard: Record<string, CharacterVoice[]>;
  loading: boolean;
  overrides: Record<string, string>;
  onOverride: (speaker: string, voiceId: string) => void;
}) {
  const t = useTranslations('scriptStudio');
  if (!speakers.length) return null;
  const anyClone = speakers.some((link) => {
    const picked = overrides[link.speaker];
    const voices = link.cardId ? (voicesByCard[link.cardId] ?? []) : [];
    const voice =
      picked !== undefined
        ? voices.find((v) => v.id === picked)
        : defaultSpeakerVoice(voices, link.lookId)?.voice;
    return voice?.source === 'clone';
  });
  return (
    <div className="flex flex-col gap-1.5">
      <p className="flex items-center gap-2 text-xs font-medium text-muted">
        {t('dubSpeakers')}
        {loading ? <Spinner className="size-3" /> : null}
      </p>
      <ul className="flex max-h-56 flex-col gap-2 overflow-y-auto rounded-[var(--radius-sm)] border border-border bg-surface-soft p-2">
        {speakers.map((link) => {
          const voices = link.cardId ? (voicesByCard[link.cardId] ?? []) : [];
          const resolved = defaultSpeakerVoice(voices, link.lookId);
          const picked = overrides[link.speaker];
          const value = picked !== undefined ? picked : (resolved?.voice.id ?? '');
          const source =
            picked !== undefined
              ? picked
                ? t('dubSourcePicked')
                : t('dubSourceGlobal')
              : resolved
                ? resolved.source === 'look'
                  ? t('dubSourceLook')
                  : t('dubSourceDefault')
                : link.cardId
                  ? t('dubSourceNoVoices')
                  : t('dubSourceUnlinked');
          return (
            <li key={link.speaker} className="grid grid-cols-[minmax(0,8rem)_1fr] items-end gap-2">
              <div className="min-w-0 pb-2 text-sm">
                <p className="truncate font-medium">{link.speaker || t('dubNarration')}</p>
                <p className="text-[11px] text-muted">
                  {t('dubLines', { count: link.lines })} · {source}
                </p>
              </div>
              <Select
                label={t('dubVoice')}
                value={value}
                disabled={!voices.length}
                onChange={(event) => onOverride(link.speaker, event.target.value)}
                options={[
                  ...voices.map((voice) => ({
                    value: voice.id,
                    label: voice.is_default
                      ? `${voice.name}（${t('dubDefaultVoice')}）`
                      : voice.name,
                  })),
                  { value: '', label: t('dubGlobalVoice') },
                ]}
              />
            </li>
          );
        })}
      </ul>
      {anyClone ? <p className="text-xs text-amber">{t('dubCloneNote')}</p> : null}
    </div>
  );
}
