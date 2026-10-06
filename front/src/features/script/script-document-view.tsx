'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { Fragment, useEffect, useState } from 'react';

import { CharacterDescribeDialog } from '@/components/characters/character-describe-dialog';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import type { Character, Scene } from '@/lib/api/types';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import { characterHeroUrl } from '@/lib/characters';
import { useResource } from '@/lib/use-resource';

import type { ScriptCharacter, ScriptDocument, ScriptScene } from './api';
import { EditableInlineText } from './editable-text';
import { ScriptBlockRow, ScriptLegend } from './script-block';
import {
  breakpointKey,
  breakpointOrdinalInScene,
  resolveBreakpointHref,
  trailingBreakpoint,
  type BreakpointVideoBinding,
} from './script-breakpoint';
import { ScriptLinkPicker } from './script-link-picker';
import { resolveBreakpointRefs, sceneImagePrompt } from './script-prompts';
import type { BatchItemKind, BatchItemState } from './use-script-batch';

function sceneCloserChip({
  document,
  scene,
  episodeId,
  videoBindings,
}: {
  document: ScriptDocument;
  scene: ScriptScene;
  episodeId?: string;
  videoBindings?: Record<string, BreakpointVideoBinding>;
}) {
  const closer = trailingBreakpoint(scene);
  if (!closer) return null;
  return resolveBreakpointHref({
    episodeId,
    key: closer.key,
    ...resolveBreakpointRefs(document, scene, closer.blockIndex),
    binding: videoBindings?.[closer.key],
  });
}

/**
 * The full script, top to bottom: characters, then every scene in order with
 * its blocks colour-coded by type. Always renders the *whole* current
 * document — there is no diff view, matching the requirement that only the
 * final, merged script for whichever turn is selected is ever shown.
 *
 * `onLink` is only passed while viewing the episode's true latest turn
 * (see `ScriptEditor`) — linking is a structural edit to `episode.script_json`
 * itself, so it makes no sense against a browsed historical snapshot; when
 * omitted, chips/headings render without the picker (and without its
 * 新建角色卡 / 新建场景卡, which links the new card to this episode).
 *
 * `onSaveContent` is the same "only while viewing the latest turn" story,
 * for hand-editing the copy itself (logline, character traits, block text)
 * rather than linking: every commit rebuilds the *entire* document with
 * just the one field changed and hands it up whole, since the backend
 * re-validates/bounds the whole document on every save (see `ScriptEditor`).
 */
function thumbUrl(
  kind: 'character' | 'scene',
  refId: string | null,
  characters: Character[],
  scenes: Scene[],
): string | null {
  if (!refId) return null;
  if (kind === 'character') {
    const character = characters.find((item) => item.id === refId);
    return character ? characterHeroUrl(character) : null;
  }
  const scene = scenes.find((item) => item.id === refId);
  return scene?.reference_assets?.[0]?.url ?? null;
}

function AssetThumb({ url, item }: { url: string | null; item: BatchItemState | null }) {
  const generating =
    item?.status === 'queued' || item?.status === 'submitting' || item?.status === 'running';
  return (
    <div className="relative size-14 shrink-0 overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface">
      {url ? <Image src={url} alt="" fill sizes="56px" className="object-cover" /> : null}
      {generating ? (
        <div className="absolute inset-0 grid place-items-center bg-surface/70">
          <Spinner />
        </div>
      ) : null}
    </div>
  );
}

export function ScriptDocumentView({
  document,
  episodeId,
  onLink,
  onSaveContent,
  videoBindings,
  itemByKey,
  onRetryImage,
  libraryRevision = 0,
}: {
  document: ScriptDocument;
  episodeId?: string;
  onLink?: (
    update:
      | { kind: 'character'; name: string; refId: string | null; variantId?: string | null }
      | { kind: 'scene'; heading: string; refId: string | null; variantId?: string | null },
  ) => void;
  onSaveContent?: (next: ScriptDocument) => void;
  /** Drafts already linked to this episode, keyed by `breakpointKey`. */
  videoBindings?: Record<string, BreakpointVideoBinding>;
  itemByKey?: (kind: BatchItemKind, id: string) => BatchItemState | null;
  onRetryImage?: (kind: 'character' | 'scene', source: ScriptCharacter | ScriptScene) => void;
  libraryRevision?: number;
}) {
  const t = useTranslations('scriptStudio');
  const { notify } = useToast();
  const characters = useResource<Character[]>('/v1/characters');
  const scenes = useResource<Scene[]>('/v1/scenes');

  useEffect(() => {
    if (!libraryRevision) return;
    characters.refetch();
    scenes.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [libraryRevision]);

  const characterItems = characters.data ?? [];
  // 「同步到角色库」: the linked card whose profile is being drafted from this script.
  const [syncCardId, setSyncCardId] = useState<string | null>(null);
  const syncCard = characterItems.find((item) => item.id === syncCardId) ?? null;
  const sceneItems = scenes.data ?? [];

  const saveLogline = (next: string) => onSaveContent?.({ ...document, logline: next });

  const saveCharacterTraits = (characterIndex: number, next: string) => {
    if (!onSaveContent) return;
    const nextCharacters = document.characters.map((character, index) =>
      index === characterIndex ? { ...character, traits: next } : character,
    );
    onSaveContent({ ...document, characters: nextCharacters });
  };

  const saveBlockText = (sceneIndex: number, blockIndex: number, next: string) => {
    if (!onSaveContent) return;
    const nextScenes = document.scenes.map((scene, sIndex) => {
      if (sIndex !== sceneIndex) return scene;
      const nextBlocks = scene.blocks.map((block, bIndex) =>
        bIndex === blockIndex ? { ...block, text: next } : block,
      );
      return { ...scene, blocks: nextBlocks };
    });
    onSaveContent({ ...document, scenes: nextScenes });
  };

  // 新建角色卡 / 新建场景卡: a text-only card from the script's own copy,
  // linked at once; its images are made in the card's workspace (去创作).
  const createCard = async (
    source:
      { kind: 'character'; character: ScriptCharacter } | { kind: 'scene'; scene: ScriptScene },
  ): Promise<string | null> => {
    if (!onLink) return null;
    try {
      if (source.kind === 'character') {
        const { character } = source;
        const card = await api.post<Character>('/v1/characters', {
          name: character.name.slice(0, 80),
          description: character.traits.trim().slice(0, 2000) || null,
        });
        onLink({ kind: 'character', name: character.name, refId: card.id });
        characters.refetch();
        notify(t('cardCreated', { name: card.name }), 'success');
        return card.id;
      }
      const { scene } = source;
      const card = await api.post<Scene>('/v1/scenes', {
        name: scene.heading.slice(0, 80),
        description: sceneImagePrompt(scene).slice(0, 2000),
      });
      onLink({ kind: 'scene', heading: scene.heading, refId: card.id });
      scenes.refetch();
      notify(t('cardCreated', { name: card.name }), 'success');
      return card.id;
    } catch (error) {
      notify(isApiError(error) ? error.message : t('unavailable'), 'error');
      return null;
    }
  };

  const scenePickerFor = (scene: ScriptScene) =>
    onLink ? (
      <ScriptLinkPicker
        kind="scene"
        refId={scene.ref_id}
        variantId={scene.variant_id ?? null}
        refreshKey={libraryRevision}
        onChange={(refId, variantId) =>
          onLink({ kind: 'scene', heading: scene.heading, refId, variantId })
        }
        onCreate={episodeId ? () => createCard({ kind: 'scene', scene }) : undefined}
      />
    ) : undefined;

  if (document.scenes.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <ScriptLegend />
        <p className="text-sm text-muted">{t('emptyScript')}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <ScriptLegend />

      {document.logline || onSaveContent ? (
        <EditableInlineText
          value={document.logline}
          onCommit={saveLogline}
          editable={!!onSaveContent}
          className="block text-sm italic text-muted"
          ariaLabel={t('logline')}
          title={onSaveContent ? t('editHint') : undefined}
        />
      ) : null}

      {document.characters.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            {t('characters')}
          </h3>
          <div className="flex flex-wrap gap-2">
            {document.characters.map((character, characterIndex) => {
              const batchItem = itemByKey?.('character', character.name) ?? null;
              return (
                <div
                  key={character.name}
                  className="flex gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2"
                >
                  <AssetThumb
                    url={thumbUrl(
                      'character',
                      character.character_ref_id,
                      characterItems,
                      sceneItems,
                    )}
                    item={batchItem}
                  />
                  <div className="flex min-w-0 flex-col gap-1.5">
                    <p className="text-sm font-medium">{character.name}</p>
                    {character.traits || onSaveContent ? (
                      <EditableInlineText
                        value={character.traits}
                        onCommit={(next) => saveCharacterTraits(characterIndex, next)}
                        editable={!!onSaveContent}
                        className="mt-0.5 block max-w-[24ch] text-xs text-muted"
                        ariaLabel={t('characters')}
                        title={onSaveContent ? t('editHint') : undefined}
                      />
                    ) : null}
                    {batchItem?.status === 'running' ||
                    batchItem?.status === 'submitting' ||
                    batchItem?.status === 'queued' ? (
                      <p className="text-[11px] text-muted">{t('batchItemGenerating')}</p>
                    ) : null}
                    {batchItem?.status === 'failed' && onRetryImage ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => onRetryImage('character', character)}
                      >
                        {t('batchRetry')}
                      </Button>
                    ) : null}
                    {onLink && episodeId && character.character_ref_id ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="self-start"
                        onClick={() => setSyncCardId(character.character_ref_id)}
                      >
                        {t('syncToLibrary')}
                      </Button>
                    ) : null}
                    {onLink ? (
                      <ScriptLinkPicker
                        kind="character"
                        refId={character.character_ref_id}
                        variantId={character.look_id ?? null}
                        refreshKey={libraryRevision}
                        onChange={(refId, variantId) =>
                          onLink({ kind: 'character', name: character.name, refId, variantId })
                        }
                        onCreate={
                          episodeId ? () => createCard({ kind: 'character', character }) : undefined
                        }
                      />
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-5">
        {document.scenes.map((scene, sceneIndex) => {
          const closerChip = sceneCloserChip({ document, scene, episodeId, videoBindings });
          return (
            <div key={sceneIndex} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <AssetThumb
                  url={thumbUrl('scene', scene.ref_id, characterItems, sceneItems)}
                  item={itemByKey?.('scene', scene.heading) ?? null}
                />
                <h3 className="text-sm font-semibold">{scene.heading}</h3>
                {itemByKey?.('scene', scene.heading)?.status === 'failed' && onRetryImage ? (
                  <Button size="sm" variant="ghost" onClick={() => onRetryImage('scene', scene)}>
                    {t('batchRetry')}
                  </Button>
                ) : null}
                {scenePickerFor(scene)}
              </div>
              <div className="flex flex-col gap-1.5">
                {scene.blocks.map((block, blockIndex) => {
                  const key =
                    block.type === 'breakpoint'
                      ? breakpointKey(scene.heading, breakpointOrdinalInScene(scene, blockIndex))
                      : null;
                  const chip =
                    key !== null
                      ? resolveBreakpointHref({
                          episodeId,
                          key,
                          ...resolveBreakpointRefs(document, scene, blockIndex),
                          binding: videoBindings?.[key],
                        })
                      : undefined;
                  const previous = scene.blocks[blockIndex - 1];
                  const showSegmentScenePicker =
                    Boolean(onLink) &&
                    block.type !== 'breakpoint' &&
                    previous?.type === 'breakpoint';
                  return (
                    <Fragment key={blockIndex}>
                      {showSegmentScenePicker ? (
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          <AssetThumb
                            url={thumbUrl('scene', scene.ref_id, characterItems, sceneItems)}
                            item={itemByKey?.('scene', scene.heading) ?? null}
                          />
                          {scenePickerFor(scene)}
                        </div>
                      ) : null}
                      <ScriptBlockRow
                        block={block}
                        onSave={
                          onSaveContent
                            ? (next) => saveBlockText(sceneIndex, blockIndex, next)
                            : undefined
                        }
                        breakpointVideoHref={chip?.href}
                        viewGenerated={chip?.viewGenerated}
                      />
                    </Fragment>
                  );
                })}
                {closerChip ? (
                  <ScriptBlockRow
                    block={{ type: 'breakpoint', character: null, text: '' }}
                    breakpointVideoHref={closerChip.href}
                    viewGenerated={closerChip.viewGenerated}
                  />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      {syncCard && episodeId ? (
        <CharacterDescribeDialog
          open
          onClose={() => setSyncCardId(null)}
          characterId={syncCard.id}
          episodeId={episodeId}
          current={{
            description: syncCard.description ?? '',
            voiceDescription: syncCard.voice_description ?? '',
          }}
          onApply={async (next) => {
            await api.patch(`/v1/characters/${syncCard.id}`, {
              ...(next.description !== undefined ? { description: next.description } : {}),
              ...(next.voiceDescription !== undefined
                ? { voice_description: next.voiceDescription }
                : {}),
            });
            characters.refetch();
          }}
        />
      ) : null}
    </div>
  );
}
