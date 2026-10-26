'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { AssetGraphWorkspace } from '@/components/asset-graph/asset-graph-workspace';
import { useAssetGraph } from '@/components/asset-graph/use-asset-graph';
import { CharacterImageStudio } from '@/components/characters/character-image-studio';
import { CharacterVoiceStudio } from '@/components/characters/character-voice-studio';
import type { CardKind } from '@/components/library/entry-actions';
import { Button } from '@/components/ui/button';
import { IconMic, IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { AGE_STAGES, type AgeStage } from '@/features/image-assets/vocabulary';
import { api } from '@/lib/api/client';
import type { AssetGraph, Character } from '@/lib/api/types';
import { cn } from '@/lib/cn';

import { CreateTab } from './create-tab';
import type { WorkspaceTab } from './tabs';

const PENDING_POLL_MS = 3000;

/**
 * A card's workspace (`/create/{characters|scenes|props}/[id]`): 创作 — the
 * slot board (AC-5) — then 图谱 and, for a character, 音色 (the relation
 * graph, RL-P5/P8). All tabs share one graph store; while jobs are filing
 * into the card it is refetched so finished images replace the placeholders.
 */
export function AssetWorkspace({
  kind,
  initial,
  initialTab,
  initialVariantId,
  initialSlotId,
  initialSkillId,
}: {
  kind: CardKind;
  initial: AssetGraph;
  initialTab?: WorkspaceTab | null;
  /** `?look=` / `?variant=`. */
  initialVariantId?: string | null;
  /** `?slot=`: preselect a 创作 slot. */
  initialSlotId?: string | null;
  /** `?skillId=`: the style skill the 创作 slot panel starts on. */
  initialSkillId?: string | null;
}) {
  const t = useTranslations('assetWorkspace');
  const tGraph = useTranslations('assetGraph');
  const tChar = useTranslations('characters');
  const tPreset = useTranslations('remixPage.presets');
  const store = useAssetGraph(kind, initial);
  const { graph, busy, error, actions, clearError } = store;
  const tabs: WorkspaceTab[] =
    kind === 'character' ? ['create', 'looks', 'voices'] : ['create', 'looks'];
  const [tab, setTab] = useState<WorkspaceTab>(
    initialTab && tabs.includes(initialTab) ? initialTab : 'create',
  );
  const [voiceSubView, setVoiceSubView] = useState<'studio' | 'graph'>('studio');
  const [studioCharacter, setStudioCharacter] = useState<Character | null>(null);
  const [imageStudioOpen, setImageStudioOpen] = useState(false);

  // A look (and slot) the graph asked to generate for — the 创作 tab mounts
  // on it. The graph's 生成 / 生成定妆照 land here, never in a studio.
  const [createTarget, setCreateTarget] = useState<{
    variantId: string;
    slotId: string | null;
  } | null>(null);
  const openCreate = (variantId: string, slotId: string | null = null) => {
    setCreateTarget({ variantId, slotId });
    setTab('create');
  };
  const defaultVariantId =
    (graph.variants ?? []).find((variant) => variant.is_default)?.id ?? graph.variants?.[0]?.id;

  const openCharacterImageStudio = async () => {
    try {
      const full = await api.get<Character>(`/v1/characters/${graph.card_id}`);
      setStudioCharacter(full);
    } catch {
      setStudioCharacter(null);
    }
    setImageStudioOpen(true);
  };

  const pendingCount = graph.pending?.length ?? 0;
  const { refresh } = actions;
  useEffect(() => {
    if (!pendingCount) return;
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, PENDING_POLL_MS);
    return () => window.clearInterval(timer);
  }, [pendingCount, refresh]);

  if (kind === 'character' && imageStudioOpen) {
    const fallbackChar: Character = studioCharacter ?? {
      id: graph.card_id,
      name: graph.name,
      gender: graph.gender ?? null,
      age: graph.age ?? null,
      personality: graph.personality ?? null,
      source: 'library',
      description: graph.description ?? null,
      voice_description: graph.voice_description ?? null,
      looks: graph.variants ?? [],
      anchor_entry_id: graph.anchor_entry_id ?? null,
      status: 'draft',
      visibility: 'private',
      access_credits: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    return (
      <CharacterImageStudio
        character={fallbackChar}
        initialStyleSkillId={initialSkillId}
        onConfirmed={(updated) => {
          setStudioCharacter(updated);
          void refresh();
        }}
        onCancel={() => {
          setImageStudioOpen(false);
          void refresh();
        }}
      />
    );
  }

  const ageKey = graph.age as AgeStage | null | undefined;
  const ageLabel = ageKey && ageKey in AGE_STAGES ? tPreset(AGE_STAGES[ageKey].labelKey) : null;
  const genderLabel = graph.gender ? tChar(`genderOptions.${graph.gender}`) : null;

  return (
    <div className="flex flex-col gap-4">
      {kind === 'character' ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3.5">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-1.5">
              {genderLabel ? <Badge tone="neutral">{genderLabel}</Badge> : null}
              {ageLabel ? <Badge tone="neutral">{ageLabel}</Badge> : null}
              {graph.personality ? (
                <span className="text-xs font-medium text-primary">{graph.personality}</span>
              ) : null}
            </div>
            {graph.description ? (
              <p className="line-clamp-1 text-xs text-muted">
                <span className="font-medium text-text">{tChar('readOnlyImagePromptLabel')}：</span>
                {graph.description}
              </p>
            ) : null}
            {graph.voice_description ? (
              <p className="line-clamp-1 text-xs text-muted">
                <span className="font-medium text-text">{tChar('readOnlyVoicePromptLabel')}：</span>
                {graph.voice_description}
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={<IconSparkle className="size-3.5" />}
              onClick={() => void openCharacterImageStudio()}
            >
              {tChar('openImageStudioAction')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<IconMic className="size-3.5" />}
              onClick={() => {
                setTab('voices');
                setVoiceSubView('studio');
              }}
            >
              {tChar('openVoiceStudioAction')}
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div
          role="tablist"
          aria-label={tGraph('tabsLabel')}
          className="flex gap-1 self-start rounded-[var(--radius-sm)] bg-surface-soft p-1"
        >
          {tabs.map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={tab === value}
              onClick={() => setTab(value)}
              className={cn(
                'rounded-[var(--radius-sm)] px-3 py-1.5 text-sm transition-colors focus-visible:outline-2',
                tab === value ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-text',
              )}
            >
              {value === 'create'
                ? t('tabCreate')
                : value === 'looks'
                  ? t(`tabGraph.${kind}`, { count: (graph.variants ?? []).length })
                  : tGraph('tabVoices', { count: (graph.voices ?? []).length })}
            </button>
          ))}
        </div>

        {kind === 'character' && tab === 'voices' ? (
          <div className="flex gap-1 rounded-[var(--radius-sm)] bg-surface-soft p-1 text-xs">
            <button
              type="button"
              onClick={() => setVoiceSubView('studio')}
              className={cn(
                'rounded-[var(--radius-sm)] px-2.5 py-1 transition-colors',
                voiceSubView === 'studio'
                  ? 'bg-surface font-medium text-text shadow-sm'
                  : 'text-muted hover:text-text',
              )}
            >
              {tChar('voiceStudioBadge')}
            </button>
            <button
              type="button"
              onClick={() => setVoiceSubView('graph')}
              className={cn(
                'rounded-[var(--radius-sm)] px-2.5 py-1 transition-colors',
                voiceSubView === 'graph'
                  ? 'bg-surface font-medium text-text shadow-sm'
                  : 'text-muted hover:text-text',
              )}
            >
              {tChar('voiceGraphSubTab')}
            </button>
          </div>
        ) : null}
      </div>

      {tab === 'create' ? (
        <>
          {error ? (
            <ErrorNotice
              title={error}
              action={
                <Button size="sm" variant="ghost" onClick={clearError}>
                  {tGraph('dismiss')}
                </Button>
              }
            />
          ) : null}
          <CreateTab
            kind={kind}
            graph={graph}
            actions={actions}
            busy={busy}
            initialVariantId={createTarget?.variantId ?? initialVariantId}
            initialSlotId={createTarget ? createTarget.slotId : initialSlotId}
            initialSkillId={initialSkillId}
          />
        </>
      ) : kind === 'character' && tab === 'voices' && voiceSubView === 'studio' ? (
        <CharacterVoiceStudio
          character={{
            id: graph.card_id,
            name: graph.name,
            gender: graph.gender ?? null,
            age: graph.age ?? null,
            personality: graph.personality ?? null,
            source: 'library',
            description: graph.description ?? null,
            voice_description: graph.voice_description ?? null,
            looks: graph.variants ?? [],
            anchor_entry_id: graph.anchor_entry_id ?? null,
            status: 'draft',
            visibility: 'private',
            access_credits: 0,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }}
          looks={graph.variants ?? []}
          initialVoices={graph.voices ?? []}
          onCharacterUpdated={() => {
            void refresh();
          }}
          onVoicesChanged={() => {
            void refresh();
          }}
        />
      ) : (
        <AssetGraphWorkspace
          kind={kind}
          store={store}
          tab={tab}
          initialLookId={initialVariantId}
          onOpenCreate={(variant) => openCreate(variant.id)}
          onOpenPortrait={
            kind === 'character' && defaultVariantId
              ? () => openCreate(defaultVariantId, 'portrait')
              : undefined
          }
        />
      )}
    </div>
  );
}
