'use client';

import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react';

import type { WorkflowEdgeKind } from '@/lib/api/admin-types';

export interface WorkflowEdgeData {
  kind: WorkflowEdgeKind;
  [key: string]: unknown;
}

const KIND_STYLE: Record<WorkflowEdgeKind, React.CSSProperties> = {
  sequential: { stroke: 'var(--muted)', strokeWidth: 1.5 },
  retry: { stroke: 'var(--amber)', strokeWidth: 1.5, strokeDasharray: '6 4' },
  parallel: { stroke: 'var(--primary)', strokeWidth: 2 },
};

/** Kind is the only thing distinguishing an edge visually: solid grey for the
 * normal happy path, dashed amber for a loop back into `route_score`
 * (`kind="retry"`), solid blue for a fan-out branch (`kind="parallel"`). */
export function WorkflowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  data,
  label,
}: EdgeProps & { data?: WorkflowEdgeData }) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const kind = data?.kind ?? 'sequential';

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={{ ...KIND_STYLE[kind], opacity: selected ? 1 : 0.75 }} />
      {label ? (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
            className="rounded border border-border bg-surface px-1 text-[10px] text-muted"
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
