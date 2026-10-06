'use client';

import { useTranslations } from 'next-intl';

import { VoicePlayButton } from '@/components/asset-graph/voice-play-button';
import { Badge } from '@/components/ui/primitives';
import type { AssetVariant, CharacterVoice } from '@/lib/api/types';

/**
 * A character card's voices on its unlocked detail — they unlock with the
 * card. Read-only: name, kind, model · voice, use, the looks each voice goes
 * with and its preview. The clone sample itself never reaches the buyer.
 */
export function UnlockedVoicesSection({
  voices,
  looks,
}: {
  voices: CharacterVoice[];
  looks: AssetVariant[];
}) {
  const t = useTranslations('skillLibrary');
  const tGraph = useTranslations('assetGraph');
  const tVariants = useTranslations('assetVariants');
  if (voices.length === 0) return null;
  const lookName = new Map(looks.map((look) => [look.id, look.name]));

  return (
    <section>
      <h3 className="text-sm font-semibold">{t('voicesTitle')}</h3>
      <p className="mt-1 text-xs text-muted">{t('voicesHint')}</p>
      <ul className="mt-2 divide-y divide-border overflow-hidden rounded-[var(--radius-sm)] border border-border">
        {voices.map((voice) => {
          const facts = [
            voice.source === 'clone' ? tGraph('voiceClone') : tGraph('voicePreset'),
            voice.model && voice.voice ? `${voice.model} · ${voice.voice}` : null,
            voice.attributes?.age_stage
              ? tVariants(`ageStage.${voice.attributes.age_stage}`)
              : null,
            voice.attributes?.use ? tGraph(`voiceUse.${voice.attributes.use}`) : null,
            voice.attributes?.emotion ?? null,
          ].filter(Boolean);
          const bound = (voice.look_ids ?? [])
            .map((id) => lookName.get(id))
            .filter((name): name is string => Boolean(name));
          return (
            <li key={voice.id} className="flex items-start gap-3 bg-surface-soft px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-sm text-text">{voice.name}</span>
                  {voice.is_default ? <Badge tone="primary">{tGraph('defaultBadge')}</Badge> : null}
                </div>
                <p className="mt-0.5 text-xs text-muted">{facts.join(' · ')}</p>
                {voice.description ? (
                  <p className="mt-0.5 whitespace-pre-wrap text-xs text-muted">
                    {voice.description}
                  </p>
                ) : null}
                {bound.length > 0 ? (
                  <p className="mt-0.5 text-xs text-muted">
                    {t('voiceLooks', { names: bound.join('、') })}
                  </p>
                ) : null}
              </div>
              {voice.preview?.url ? (
                <VoicePlayButton url={voice.preview.url} className="shrink-0" />
              ) : (
                <span className="shrink-0 text-[11px] text-muted">{tGraph('noPreview')}</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
