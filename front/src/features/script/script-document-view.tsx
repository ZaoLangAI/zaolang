'use client';

import { useTranslations } from 'next-intl';

import type { ScriptBlockType, ScriptCharacter, ScriptDocument, ScriptScene } from './api';
import { EditableInlineText } from './editable-text';
import { ScriptBlockRow, ScriptLegend } from './script-block';
import {
  breakpointKey,
  breakpointOrdinalInScene,
  breakpointSegmentBlocks,
  resolveBreakpointHref,
  trailingBreakpoint,
  type BreakpointVideoBinding,
} from './script-breakpoint';
import { ScriptLinkPicker } from './script-link-picker';

/** Seed prompt for a character's auto-created/updated image: the traits the
 * writer already gave it, falling back to the bare name for a character
 * with none yet rather than submitting an empty prompt. `traits` itself is
 * appearance-first now (gender/age/skin tone/hair/build/attire, personality
 * only after — see `copywriter._CHARACTER_APPEARANCE_RULE`), so this seed
 * already reads as a character-portrait prompt rather than a personality
 * blurb without any change needed here. */
function characterImagePrompt(character: ScriptCharacter): string {
  return character.traits.trim() || character.name;
}

/** Seed prompt for a scene's auto-created/updated image: the heading alone
 * ("内景·咖啡馆-日") is not evocative enough on its own, so it's paired with
 * every non-empty `scene`-type block in the scene, in order — not just the
 * first one, since a scene can carry more than one pure environment
 * description (e.g. a later lighting/weather beat) and dropping the rest
 * left the seed prompt incomplete. `scene` is the block type reserved for
 * pure static environment description (see `copywriter._BLOCK_TYPE_RULES`).
 * Deliberately never an `action` block: those describe character movement,
 * which conflicts with the scene-asset pipeline's no-people requirement
 * (`planner._ASSET_KIND_BRIEF[SCENE]`) — falling back to the bare heading
 * here is still safer than seeding a prompt with a character in it. */
function sceneImagePrompt(scene: ScriptScene): string {
  const envTexts = scene.blocks
    .filter((block) => block.type === 'scene' && block.text.trim())
    .map((block) => block.text.trim());
  return envTexts.length ? `${scene.heading}，${envTexts.join('，')}` : scene.heading;
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

/** One labelled section of `breakpointSegmentPrompt`'s output, in render
 * order. `scene`'s `label` is unused — that section is always headed by the
 * scene's own heading instead (see the `type === 'scene'` branch below). */
const _SEGMENT_PROMPT_SECTIONS: { type: ScriptBlockType; label: string }[] = [
  { type: 'scene', label: '' },
  { type: 'action', label: '动作：' },
  { type: 'camera', label: '镜头：' },
  { type: 'dialogue', label: '台词：' },
];

/**
 * Seeds the video studio's prompt field with the segment's own copy —
 * without this, "生成视频片段" opens an empty prompt and the writer has to
 * retype what the script already says.
 *
 * Grouped by block type into labelled sections (场景/动作/镜头/台词) instead
 * of flattening every block into one "；"-joined sentence: a video generator
 * benefits from camera direction, action and dialogue being distinguishable
 * from each other rather than run together, and grouping (instead of
 * dropping) every matching block per type is what keeps the seed a complete
 * prompt when a segment has more than one block of the same type. Each
 * section joins its own blocks with "；"; a dialogue line is still prefixed
 * with the speaker's name (matching how it already reads in the document).
 * Sections with no matching block are omitted entirely. Order is fixed —
 * 场景 (scene heading + any `scene` blocks) sets the subject before 动作,
 * 镜头 gives the camera instruction, 台词 comes last, matching how a video
 * prompt is usually read. Capped by `create/new/page.tsx`'s own
 * `PROMPT_MAX_LENGTH` slice, so no length handling is needed here.
 */
function breakpointSegmentPrompt(scene: ScriptScene, breakpointBlockIndex: number): string {
  const blocks = breakpointSegmentBlocks(scene, breakpointBlockIndex).filter((block) =>
    block.text.trim(),
  );
  const sections = _SEGMENT_PROMPT_SECTIONS.map(({ type, label }) => {
    const texts = blocks
      .filter((block) => block.type === type)
      .map((block) =>
        type === 'dialogue' && block.character
          ? `${block.character}：${block.text.trim()}`
          : block.text.trim(),
      );
    // 场景 always renders (the heading alone is still a usable seed), every
    // other section is dropped entirely when this segment has no such block.
    if (type === 'scene') {
      return texts.length ? `${scene.heading}，${texts.join('；')}` : scene.heading;
    }
    return texts.length ? `${label}${texts.join('；')}` : null;
  }).filter((section): section is string => section !== null);
  return sections.join('\n');
}

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
    prompt: breakpointSegmentPrompt(scene, closer.blockIndex),
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
  videoBindings,
}: {
  document: ScriptDocument;
  episodeId?: string;
  onLink?: (
    update:
      | { kind: 'character'; name: string; refId: string | null }
      | { kind: 'scene'; heading: string; refId: string | null },
  ) => void;
  onSaveContent?: (next: ScriptDocument) => void;
  /** Drafts already linked to this episode, keyed by `breakpointKey`. */
  videoBindings?: Record<string, BreakpointVideoBinding>;
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
        {document.scenes.map((scene, sceneIndex) => {
          const closerChip = sceneCloserChip({ document, scene, episodeId, videoBindings });
          return (
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
                          prompt: breakpointSegmentPrompt(scene, blockIndex),
                          binding: videoBindings?.[key],
                        })
                      : undefined;
                  return (
                    <ScriptBlockRow
                      key={blockIndex}
                      block={block}
                      onSave={
                        onSaveContent
                          ? (next) => saveBlockText(sceneIndex, blockIndex, next)
                          : undefined
                      }
                      breakpointVideoHref={chip?.href}
                      viewGenerated={chip?.viewGenerated}
                    />
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
    </div>
  );
}
