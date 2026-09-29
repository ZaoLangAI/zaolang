'use client';

import {
  BaseEdge,
  Handle,
  Position,
  getBezierPath,
  type EdgeProps,
  type NodeProps,
} from '@xyflow/react';

import { cn } from '@/lib/cn';
import { anchorKindOf } from '@/components/admin/workflows/workflow-anchors';
import type { WorkflowNodeData } from '@/components/admin/workflows/workflow-node';

/**
 * A non-interactive marker: the canvas's own visible answer to "where does
 * this graph start" / "where does every path end up". Never draggable,
 * selectable, connectable or deletable — see `computeAnchors` for why it
 * never reaches `graph_json`.
 */
export function WorkflowAnchorNode({ data }: NodeProps & { data: WorkflowNodeData }) {
  const kind = anchorKindOf(data);
  return (
    <div
      className={cn(
        'flex items-center justify-center rounded-full border px-4 py-2 text-xs font-semibold shadow-card',
        kind === 'start'
          ? 'border-primary/40 bg-primary/10 text-primary'
          : 'border-text/30 bg-surface-soft text-text',
      )}
    >
      {kind === 'end' ? (
        <Handle
          type="target"
          position={Position.Left}
          className="!size-2 !border-border !bg-surface"
        />
      ) : null}
      {data.label}
      {kind === 'start' ? (
        <Handle
          type="source"
          position={Position.Right}
          className="!size-2 !border-border !bg-surface"
        />
      ) : null}
    </div>
  );
}

/** Dashed, muted — deliberately less prominent than a real `WorkflowEdge` so
 * it reads as scaffolding, not as another wired connection. */
export function WorkflowAnchorEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
}: EdgeProps) {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  return (
    <BaseEdge
      path={edgePath}
      style={{ stroke: 'var(--border)', strokeWidth: 1.25, strokeDasharray: '3 3', opacity: 0.6 }}
    />
  );
}
