'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  CHARACTER_ENTRY_TYPES,
  PROP_ENTRY_TYPES,
  EntryCard,
  SCENE_ENTRY_TYPES,
  type CardKind,
} from '@/components/library/entry-actions';
import { MediaLightbox } from '@/components/ui/media-lightbox';
import { Badge } from '@/components/ui/primitives';
import type { AssetEntry, AssetGenerateResponse, AssetGraph, AssetVariant } from '@/lib/api/types';
import { cn } from '@/lib/cn';

import type { AssetGraphActions } from '../use-asset-graph';
import { versionIndex } from '../versions';
import { GeneratePanel } from './generate-panel';
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
  onSelectVersion,
  onDeleted,
  onGenerated,
}: {
  graph: AssetGraph;
  kind: CardKind;
  entry: AssetEntry;
  variant: AssetVariant;
  busy: boolean;
  actions: AssetGraphActions;
  onSelectEdge: (edgeId: string) => void;
  /** Show another version of this image here. */
  onSelectVersion: (entryId: string) => void;
  onDeleted: () => void;
  onGenerated: (response: AssetGenerateResponse) => void;
}) {
  const t = useTranslations('assetGraph');
  const tMedia = useTranslations('media');
  const name = useNodeNames(graph);
  const [lightbox, setLightbox] = useState(false);
  const { headOf, versions } = versionIndex(graph);
  const group = versions.get(headOf.get(entry.id) ?? entry.id) ?? [entry];
  const pendingVersions = (graph.pending ?? []).filter(
    (job) => job.mode === 'edit' && group.some((e) => e.id === job.source_entry_id),
  ).length;

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

      {group.length > 1 || pendingVersions ? (
        <InspectorSection title={t('sectionVersions', { count: group.length })}>
          <p className="text-xs text-muted">{t('versionsHint')}</p>
          <ul className="flex flex-wrap gap-1.5">
            {group.map((version) => (
              <li key={version.id}>
                <button
                  type="button"
                  aria-label={t('openVersion')}
                  aria-current={version.id === entry.id}
                  onClick={() => onSelectVersion(version.id)}
                  className={cn(
                    'relative size-16 overflow-hidden rounded-[var(--radius-sm)] border bg-surface-soft focus-visible:outline-2',
                    version.id === entry.id
                      ? 'border-primary ring-2 ring-primary/30'
                      : 'border-border',
                    version.status === 'candidate' && 'border-dashed',
                  )}
                >
                  {version.url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={version.url} alt="" className="h-full w-full object-cover" />
                  ) : null}
                  {version.status !== 'candidate' ? (
                    <span className="absolute left-0.5 top-0.5">
                      <Badge tone="primary">{t('versionCurrent')}</Badge>
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
          {pendingVersions ? (
            <p className="text-xs text-primary">
              {t('versionPending', { count: pendingVersions })}
            </p>
          ) : null}
        </InspectorSection>
      ) : null}

      <InspectorSection title={t('sectionEntry')}>
        <ul>
          <EntryCard
            entry={entry}
            variant={variant}
            variants={graph.variants ?? []}
            isAnchor={entry.id === graph.anchor_entry_id}
            entryTypes={
              kind === 'character'
                ? CHARACTER_ENTRY_TYPES
                : kind === 'prop'
                  ? PROP_ENTRY_TYPES
                  : SCENE_ENTRY_TYPES
            }
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

      <InspectorSection title={t('sectionGenerate')}>
        <GeneratePanel
          key={entry.id}
          graph={graph}
          kind={kind}
          entry={entry}
          variant={variant}
          onSubmitted={onGenerated}
        />
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
