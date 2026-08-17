'use client';

import { useTranslations } from 'next-intl';

import type { ScriptDocument } from './api';
import { ScriptBlockRow, ScriptLegend } from './script-block';
import { ScriptLinkPicker } from './script-link-picker';

/**
 * The full script, top to bottom: characters, then every scene in order with
 * its blocks colour-coded by type. Always renders the *whole* current
 * document — there is no diff view, matching the requirement that only the
 * final, merged script for whichever turn is selected is ever shown.
 *
 * `onLink` is only passed while viewing the episode's true latest turn
 * (see `ScriptEditor`) — linking is a structural edit to `episode.script_json`
 * itself, so it makes no sense against a browsed historical snapshot; when
 * omitted, chips/headings render without the picker.
 */
export function ScriptDocumentView({
  document,
  onLink,
}: {
  document: ScriptDocument;
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
