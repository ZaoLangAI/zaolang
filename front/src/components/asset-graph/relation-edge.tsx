'use client';

import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react';
import { useTranslations } from 'next-intl';

import type { RelationEdge } from './graph-model';
import { RELATION_COLOR, relationLabelKey } from './relations';

/**
 * A typed relation: coloured by its first relation, labelled with all of
 * them (a custom one by its own name). Auto edges — written by a derive or
 * adjust — are dashed; folded image hints between collapsed looks are thin,
 * dotted and unlabelled except for their count.
 */
export function RelationEdgeLine({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  data,
  markerEnd,
}: EdgeProps<RelationEdge>) {
  const t = useTranslations('assetGraph');
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const relations = data?.relations ?? [];
  const color = RELATION_COLOR[relations[0] ?? 'custom'];
  const hint = Boolean(data?.hint);
  const names = relations.map((relation) =>
    relation === 'custom' && data?.label ? data.label : t(relationLabelKey(relation)),
  );

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: hint ? 'var(--text-muted)' : color,
          strokeWidth: hint ? 1 : selected ? 3 : 2,
          strokeDasharray: hint ? '2 4' : data?.origin === 'auto' ? '6 4' : undefined,
          opacity: hint ? 0.6 : 1,
        }}
      />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            borderColor: hint ? undefined : color,
          }}
          className={
            hint
              ? 'pointer-events-none rounded border border-border bg-surface px-1 text-[10px] text-muted'
              : 'nodrag nopan rounded-full border bg-surface px-2 py-0.5 text-[10px] font-medium text-text shadow-sm'
          }
        >
          {hint ? t('hintCount', { count: data?.count ?? 1 }) : names.join(' · ')}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
