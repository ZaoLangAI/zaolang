'use client';

import { useTranslations } from 'next-intl';

import type { ScriptCharacter, ScriptDocument, ScriptScene } from './api';
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
 * the scene's first non-empty `action` block for actual visual content. */
function sceneImagePrompt(scene: ScriptScene): string {
  const action = scene.blocks.find((block) => block.type === 'action' && block.text.trim());
  return action ? `${scene.heading}，${action.text.trim()}` : scene.heading;
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
 */
export function ScriptDocumentView({
  document,
  episodeId,
  onLink,
}: {
  document: ScriptDocument;
  episodeId?: string;
  onLink?: (
    update:
      | { kind: 'character'; name: string; refId: string | null }
      | { kind: 'scene'; heading: string; refId: string | null },
  ) => void;
}) {
  const t = useTranslations('scriptStudio');

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

      {document.logline ? <p className="text-sm italic text-muted">{document.logline}</p> : null}

      {document.characters.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            {t('characters')}
          </h3>
          <div className="flex flex-wrap gap-2">
            {document.characters.map((character) => (
              <div
                key={character.name}
                className="flex flex-col gap-1.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2"
              >
                <p className="text-sm font-medium">{character.name}</p>
                {character.traits ? (
                  <p className="mt-0.5 max-w-[24ch] text-xs text-muted">{character.traits}</p>
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
                <ScriptBlockRow key={blockIndex} block={block} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
