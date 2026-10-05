'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/field';
import type { AssetGraph } from '@/lib/api/types';

import type { CardKind } from '@/components/library/entry-actions';

import { RelationFields, relationDraftValid, type RelationDraft } from '../relation-fields';
import { versionIndex } from '../versions';
import { RELATION_COLOR, relationLabelKey } from '../relations';
import { useNodeNames } from './node-names';

/** A node's incoming and outgoing relations; each opens in the edge
 * inspector. */
export function RelationsList({
  graph,
  level,
  nodeId,
  onSelectEdge,
}: {
  graph: AssetGraph;
  level: 'variant' | 'entry';
  nodeId: string;
  onSelectEdge: (edgeId: string) => void;
}) {
  const t = useTranslations('assetGraph');
  const name = useNodeNames(graph);
  // An image's relations are its whole version group's, minus the edges
  // between those versions (`versions.ts`).
  const { headOf } = versionIndex(graph);
  const group = (id: string) => (level === 'entry' ? (headOf.get(id) ?? id) : id);
  const mine = group(nodeId);
  const edges = (graph.edges ?? []).filter(
    (edge) =>
      edge.level === level &&
      group(edge.source_id) !== group(edge.target_id) &&
      (group(edge.source_id) === mine || group(edge.target_id) === mine),
  );
  if (!edges.length) return <p className="text-xs text-muted">{t('noRelations')}</p>;
  return (
    <ul className="flex flex-col gap-1.5">
      {edges.map((edge) => {
        const outgoing = group(edge.source_id) === mine;
        const other = name(level, group(outgoing ? edge.target_id : edge.source_id));
        return (
          <li key={edge.id}>
            <button
              type="button"
              onClick={() => onSelectEdge(edge.id)}
              className="flex w-full items-center gap-2 rounded-[var(--radius-sm)] border border-border px-2.5 py-1.5 text-left text-xs hover:border-border-strong focus-visible:outline-2"
            >
              <span className="shrink-0 text-muted">{outgoing ? '→' : '←'}</span>
              <span className="min-w-0 flex-1 truncate text-text">{other}</span>
              <span className="flex shrink-0 gap-1">
                {edge.relations.map((relation) => (
                  <span
                    key={relation}
                    className="rounded-full border px-1.5 text-[10px]"
                    style={{ borderColor: RELATION_COLOR[relation] }}
                  >
                    {relation === 'custom' && edge.label
                      ? edge.label
                      : t(relationLabelKey(relation))}
                  </span>
                ))}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Adds a relation without dragging — the keyboard path to the same edge a
 * handle-to-handle drag creates.
 */
export function AddRelationForm({
  graph,
  kind,
  level,
  nodeId,
  busy,
  onCreate,
}: {
  graph: AssetGraph;
  kind: CardKind;
  level: 'variant' | 'entry';
  nodeId: string;
  busy?: boolean;
  onCreate: (body: Record<string, unknown>) => Promise<unknown>;
}) {
  const t = useTranslations('assetGraph');
  const name = useNodeNames(graph);
  const [direction, setDirection] = useState<'out' | 'in'>('out');
  const [other, setOther] = useState('');
  const [draft, setDraft] = useState<RelationDraft>({ relations: [], label: '' });
  const { headOf } = versionIndex(graph);
  const self = level === 'entry' ? (headOf.get(nodeId) ?? nodeId) : nodeId;
  // Images: one option per version group (its node in the graph).
  const candidates =
    level === 'variant'
      ? (graph.variants ?? []).map((v) => v.id)
      : (graph.variants ?? []).flatMap((v) =>
          (v.entries ?? []).map((e) => e.id).filter((id) => headOf.get(id) === id),
        );
  const options = candidates.filter((id) => id !== self);
  if (!options.length) return null;

  const submit = async () => {
    const created = await onCreate({
      level,
      source_id: direction === 'out' ? self : other,
      target_id: direction === 'out' ? other : self,
      relations: draft.relations,
      label: draft.label.trim() || null,
    });
    if (created) {
      setOther('');
      setDraft({ relations: [], label: '' });
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-dashed border-border p-3">
      <div className="grid grid-cols-[auto_1fr] gap-2">
        <Select
          label={t('direction')}
          value={direction}
          onChange={(event) => setDirection(event.target.value as 'out' | 'in')}
          options={[
            { value: 'out', label: t('directionOut') },
            { value: 'in', label: t('directionIn') },
          ]}
        />
        <Select
          label={t('otherNode')}
          value={other}
          onChange={(event) => setOther(event.target.value)}
          options={[
            { value: '', label: t('pickNode') },
            ...options.map((id) => ({ value: id, label: name(level, id) })),
          ]}
        />
      </div>
      <RelationFields kind={kind} value={draft} onChange={setDraft} />
      <Button
        size="sm"
        className="self-start"
        loading={busy}
        disabled={!other || !relationDraftValid(draft)}
        onClick={() => void submit()}
      >
        {t('addRelation')}
      </Button>
    </div>
  );
}
