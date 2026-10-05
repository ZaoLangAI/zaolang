'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  CHARACTER_ENTRY_TYPES,
  EntryCard,
  SCENE_ENTRY_TYPES,
  type CardKind,
} from '@/components/library/entry-actions';
import { MediaLightbox } from '@/components/ui/media-lightbox';
import type { AssetEntry, AssetGraph, AssetVariant } from '@/lib/api/types';

import type { AssetGraphActions } from '../use-asset-graph';
import { useNodeNames } from './node-names';
import { AddRelationForm, RelationsList } from './relations-list';
import { InspectorSection } from './section';

/** A selected image: full preview, its 定稿 / type / move / anchor / remove
 * actions (`EntryCard`) and its image-level relations. */
export function EntryInspector({
  graph,
  kind,
  entry,
  variant,
  busy,
  actions,
  onSelectEdge,
  onDeleted,
}: {
  graph: AssetGraph;
  kind: CardKind;
  entry: AssetEntry;
  variant: AssetVariant;
  busy: boolean;
  actions: AssetGraphActions;
  onSelectEdge: (edgeId: string) => void;
  onDeleted: () => void;
}) {
  const t = useTranslations('assetGraph');
  const tMedia = useTranslations('media');
  const name = useNodeNames(graph);
  const [lightbox, setLightbox] = useState(false);

  return (
    <div className="flex flex-col gap-4">
      <h2 className="truncate text-base font-semibold">{name('entry', entry.id)}</h2>
      {entry.url ? (
        <button
          type="button"
          aria-label={tMedia('lightboxTitle')}
          onClick={() => setLightbox(true)}
          className="overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface-soft focus-visible:outline-2"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={entry.url} alt="" className="max-h-80 w-full object-contain" />
        </button>
      ) : null}

      <InspectorSection title={t('sectionEntry')}>
        <ul>
          <EntryCard
            entry={entry}
            variant={variant}
            variants={graph.variants ?? []}
            isAnchor={entry.id === graph.anchor_entry_id}
            entryTypes={kind === 'character' ? CHARACTER_ENTRY_TYPES : SCENE_ENTRY_TYPES}
            onUpdate={(body) => void actions.updateEntry(entry.id, body)}
            onDelete={() =>
              void actions.deleteEntry(entry.id).then((done) => {
                if (done) onDeleted();
              })
            }
            onAnchor={() => void actions.anchorEntry(entry.id)}
            onApprove={() => void actions.approveEntry(entry.id)}
            showImage={false}
          />
        </ul>
      </InspectorSection>

      <InspectorSection title={t('sectionRelations')}>
        <RelationsList graph={graph} level="entry" nodeId={entry.id} onSelectEdge={onSelectEdge} />
        <AddRelationForm
          graph={graph}
          kind={kind}
          level="entry"
          nodeId={entry.id}
          busy={busy}
          onCreate={actions.createEdge}
        />
      </InspectorSection>

      <MediaLightbox open={lightbox} src={entry.url ?? null} onClose={() => setLightbox(false)} />
    </div>
  );
}
