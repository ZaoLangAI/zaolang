'use client';

import { useTranslations } from 'next-intl';

import type { ScriptCharacter, ScriptDocument, ScriptScene } from './api';
import { EditableInlineText } from './editable-text';
import { ScriptBlockRow, ScriptLegend } from './script-block';
import { ScriptLinkPicker } from './script-link-picker';

/** Seed prompt for a character's auto-created/updated image: the traits the
 * writer already gave it, falling back to the bare name for a character
 * with none yet rather than submitting an empty prompt. */
function characterImagePrompt(character: ScriptCharacter): string {
  return character.traits.trim() || character.name;
}

/** Seed prompt for a scene's auto-created/updated image: the heading alone
 * ("内景·咖啡馆-日") is not evocative enough on its own, so it's paired with
 * the scene's first non-empty `scene`-type block — the block reserved for
 * pure static environment description (see `copywriter._BLOCK_TYPE_RULES`).
 * Deliberately not an `action` block: those describe character movement,
 * which conflicts with the scene-asset pipeline's no-people requirement
 * (`planner._ASSET_KIND_BRIEF[SCENE]`) — falling back to the bare heading
 * here is still safer than seeding a prompt with a character in it. */
function sceneImagePrompt(scene: ScriptScene): string {
  const env = scene.blocks.find((block) => block.type === 'scene' && block.text.trim());
  return env ? `${scene.heading}，${env.text.trim()}` : scene.heading;
}

/**
 * The deep link `ScriptLinkPicker`'s "生成角色图/场景图" footer entry jumps
 * out to, carrying enough context for `/create/new` to pre-fill the image
 * studio and, on success, jump back here with the new/updated link already
 * known (`InlineImageResult`'s "返回文案创作", read back in `ScriptEditor`).
 *
 * Already-linked (`targetId` set) reuses that same card instead of creating
 * another one — `subjectNameHint` is included regardless but only takes
 * effect when there is no target, i.e. when a brand-new card gets created.
 */
function buildCreateHref({
  episodeId,
  assetKind,
  prompt,
  subjectNameHint,
  targetId,
}: {
  episodeId: string;
  assetKind: 'character' | 'scene';
  prompt: string;
  subjectNameHint: string;
  targetId: string | null;
}): string {
  const params = new URLSearchParams({
    mode: 'image_creation',
    assetKind,
    prompt,
    subjectNameHint,
    returnTo: `/create/script/${episodeId}`,
    returnLinkKind: assetKind,
    returnLinkLabel: subjectNameHint,
  });
  if (targetId) {
    params.set(assetKind === 'character' ? 'targetCharacterId' : 'targetSceneId', targetId);
  }
  return `/create/new?${params.toString()}`;
}

/** A `breakpoint` block closes exactly one segment of exactly one scene (see
 * `ScriptDocument` — `breakpoint` blocks live inside `scene.blocks`, never
 * spanning scenes) — the blocks from the previous `breakpoint` (or the
 * scene's start) up to this one. Shared by `resolveBreakpointRefs` and
 * `breakpointSegmentPrompt` below so both walk the exact same slice. */
function breakpointSegmentBlocks(scene: ScriptScene, breakpointBlockIndex: number) {
  let segmentStart = 0;
  for (let index = breakpointBlockIndex - 1; index >= 0; index -= 1) {
    if (scene.blocks[index]?.type === 'breakpoint') {
      segmentStart = index + 1;
      break;
    }
  }
  return scene.blocks.slice(segmentStart, breakpointBlockIndex);
}

/**
 * Resolves which already-linked characters/scenes a breakpoint's segment
 * actually involves, so the "生成视频片段" chip only appears — and only
 * carries refs — when there's something to hand to the video studio as a
 * reference input.
 */
function resolveBreakpointRefs(
  document: ScriptDocument,
  scene: ScriptScene,
  breakpointBlockIndex: number,
): { characterIds: string[]; sceneId: string | null } {
  const names = new Set(
    breakpointSegmentBlocks(scene, breakpointBlockIndex)
      .filter((block) => block.type === 'dialogue' && block.character)
      .map((block) => block.character as string),
  );
  const characterIds = document.characters
    .filter((character) => names.has(character.name) && character.character_ref_id)
    .map((character) => character.character_ref_id as string);
  return { characterIds, sceneId: scene.ref_id };
}

/**
 * Seeds the video studio's prompt field with the segment's own copy —
 * without this, "生成视频片段" opens an empty prompt and the writer has to
 * retype what the script already says. Scene heading first for setting,
 * then every non-empty block's text in written order; a dialogue line is
 * prefixed with the speaker's name (matching how it already reads in the
 * document) since a bare line of dialogue reads as scene description
 * otherwise. Capped by `create/new/page.tsx`'s own `PROMPT_MAX_LENGTH`
 * slice, so no length handling is needed here.
 */
function breakpointSegmentPrompt(scene: ScriptScene, breakpointBlockIndex: number): string {
  const parts = breakpointSegmentBlocks(scene, breakpointBlockIndex)
    .filter((block) => block.text.trim())
    .map((block) =>
      block.type === 'dialogue' && block.character
        ? `${block.character}：${block.text.trim()}`
        : block.text.trim(),
    );
  return [scene.heading, ...parts].join('；');
}

/**
 * The video-side counterpart of `buildCreateHref` above, for the breakpoint
 * chip: `referenceCharacterIds`/`referenceSceneIds` name new params —
 * deliberately distinct from `targetCharacterId`/`targetSceneId`, which mean
 * "auto-attach the output here", not "use this as generation input". No
 * `returnTo` round-trip: unlike the image jump-out, this consumes refs that
 * are already linked, creates nothing new to report back, and video
 * generation still lands on `/jobs/[jobId]`, which has no return-link surface.
 */
function buildBreakpointVideoHref({
  characterIds,
  sceneId,
  prompt,
}: {
  characterIds: string[];
  sceneId: string | null;
  prompt: string;
}): string | undefined {
  if (characterIds.length === 0 && !sceneId) return undefined;
  const params = new URLSearchParams({ mode: 'video_creation' });
  if (prompt) params.set('prompt', prompt);
  if (characterIds.length) params.set('referenceCharacterIds', characterIds.join(','));
  if (sceneId) params.set('referenceSceneIds', sceneId);
  return `/create/new?${params.toString()}`;
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
 * omitted, chips/headings render without the picker (and without the
 * "生成角色图/场景图" jump-out, which needs `episodeId` for its `returnTo`).
 *
 * `onSaveContent` is the same "only while viewing the latest turn" story,
 * for hand-editing the copy itself (logline, character traits, block text)
 * rather than linking: every commit rebuilds the *entire* document with
 * just the one field changed and hands it up whole, since the backend
 * re-validates/bounds the whole document on every save (see `ScriptEditor`).
 */
export function ScriptDocumentView({
  document,
  episodeId,
  onLink,
  onSaveContent,
}: {
  document: ScriptDocument;
  episodeId?: string;
  onLink?: (
    update:
      | { kind: 'character'; name: string; refId: string | null }
      | { kind: 'scene'; heading: string; refId: string | null },
  ) => void;
  onSaveContent?: (next: ScriptDocument) => void;
}) {
  const t = useTranslations('scriptStudio');

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
            {document.characters.map((character, characterIndex) => (
              <div
                key={character.name}
                className="flex flex-col gap-1.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2"
              >
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
                {onLink ? (
                  <ScriptLinkPicker
                    kind="character"
                    refId={character.character_ref_id}
                    onChange={(refId) => onLink({ kind: 'character', name: character.name, refId })}
                    createHref={
                      episodeId
                        ? buildCreateHref({
                            episodeId,
                            assetKind: 'character',
                            prompt: characterImagePrompt(character),
                            subjectNameHint: character.name,
                            targetId: character.character_ref_id,
                          })
                        : undefined
                    }
                  />
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-5">
        {document.scenes.map((scene, sceneIndex) => (
          <div key={sceneIndex} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold">{scene.heading}</h3>
              {onLink ? (
                <ScriptLinkPicker
                  kind="scene"
                  refId={scene.ref_id}
                  onChange={(refId) => onLink({ kind: 'scene', heading: scene.heading, refId })}
                  createHref={
                    episodeId
                      ? buildCreateHref({
                          episodeId,
                          assetKind: 'scene',
                          prompt: sceneImagePrompt(scene),
                          subjectNameHint: scene.heading,
                          targetId: scene.ref_id,
                        })
                      : undefined
                  }
                />
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              {scene.blocks.map((block, blockIndex) => (
                <ScriptBlockRow
                  key={blockIndex}
                  block={block}
                  onSave={
                    onSaveContent
                      ? (next) => saveBlockText(sceneIndex, blockIndex, next)
                      : undefined
                  }
                  breakpointVideoHref={
                    block.type === 'breakpoint'
                      ? buildBreakpointVideoHref({
                          ...resolveBreakpointRefs(document, scene, blockIndex),
                          prompt: breakpointSegmentPrompt(scene, blockIndex),
                        })
                      : undefined
                  }
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
