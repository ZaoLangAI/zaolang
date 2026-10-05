'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import type { CardKind } from '@/components/library/entry-actions';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/primitives';
import type { AssetEdge, AssetGraph } from '@/lib/api/types';

import { RelationFields, relationDraftValid, type RelationDraft } from '../relation-fields';
import type { AssetGraphActions } from '../use-asset-graph';
import { useNodeNames } from './node-names';
import { InspectorSection } from './section';

/** A selected relation: retype or relabel it, jump to either end, delete it. */
export function EdgeInspector({
  graph,
  kind,
  edge,
  busy,
  actions,
  onSelectNode,
  onDeleted,
}: {
  graph: AssetGraph;
  kind: CardKind;
  edge: AssetEdge;
  busy: boolean;
  actions: AssetGraphActions;
  onSelectNode: (level: 'variant' | 'entry' | 'voice', id: string) => void;
  onDeleted: () => void;
}) {
  const t = useTranslations('assetGraph');
  const tActions = useTranslations('actions');
  const name = useNodeNames(graph);
  const level = edge.level;
  const [draft, setDraft] = useState<RelationDraft>({
    relations: edge.relations,
    label: edge.label ?? '',
  });
  const end = (id: string) => (
    <button
      type="button"
      onClick={() => onSelectNode(level, id)}
      className="min-w-0 truncate rounded-[var(--radius-sm)] border border-border px-2 py-1 text-left text-xs hover:border-border-strong focus-visible:outline-2"
    >
      {name(level, id)}
    </button>
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h2 className="min-w-0 flex-1 text-base font-semibold">{t('edgeTitle')}</h2>
        <Badge tone={edge.origin === 'auto' ? 'amber' : 'neutral'}>
          {edge.origin === 'auto' ? t('originAuto') : t('originManual')}
        </Badge>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        {end(edge.source_id)}
        <span className="text-muted">→</span>
        {end(edge.target_id)}
      </div>
      <InspectorSection title={t('sectionRelationType')}>
        <RelationFields
          kind={kind}
          value={draft}
          onChange={setDraft}
          voices={edge.level === 'voice'}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            loading={busy}
            disabled={!relationDraftValid(draft)}
            onClick={() =>
              void actions.updateEdge(edge.id, {
                relations: draft.relations,
                ...(draft.label.trim() ? { label: draft.label.trim() } : { clear_label: true }),
              })
            }
          >
            {t('saveRelation')}
          </Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() =>
              void actions.deleteEdge(edge.id).then((done) => {
                if (done) onDeleted();
              })
            }
          >
            {tActions('delete')}
          </Button>
        </div>
      </InspectorSection>
    </div>
  );
}
