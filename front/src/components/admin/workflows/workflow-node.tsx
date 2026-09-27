'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';

import { Badge } from '@/components/ui/primitives';
import type { NodeTypeView } from '@/lib/api/admin-types';
import { cn } from '@/lib/cn';

export interface WorkflowNodeData {
  nodeType: string;
  config: Record<string, unknown>;
  spec: NodeTypeView | undefined;
  /** The node type's name in the operator's locale. */
  label: string;
  /** The operator's own name for this instance, when they gave it one. */
  title?: string;
  /** One line naming what this node is wired to, in human terms — the bound
   * agent's name and model rather than its `ap_…` id. */
  summary?: string;
  /** Failed publish-time validation: an error names this node. */
  broken?: boolean;
  /** Hit a workflow engine failure on real jobs recently. Structurally valid
   * but, in practice, misconfigured. */
  hotspot?: boolean;
  /** Executed during the last dry run, and which port it left by. */
  tracedPort?: string | null;
  [key: string]: unknown;
}

const CATEGORY_TONE: Record<string, string> = {
  moderation: 'border-l-danger',
  context: 'border-l-primary',
  planning: 'border-l-primary',
  routing: 'border-l-amber',
  generation: 'border-l-amber',
  quality: 'border-l-success',
  control: 'border-l-muted',
  terminal: 'border-l-text',
};

/** One node card on the canvas: type badge, label, config summary, and one
 * labelled source handle per output port (`registry.NodeSpec.output_ports`)
 * so a fan-out's per-port wiring is visible without opening the panel. */
export function WorkflowNode({ data, selected }: NodeProps & { data: WorkflowNodeData }) {
  const spec = data.spec;
  const ports = spec?.output_ports ?? [];
  const traced = data.tracedPort != null;

  return (
    <div
      className={cn(
        'flex w-64 rounded-[var(--radius-md)] border border-l-4 bg-surface-raised shadow-card',
        spec ? (CATEGORY_TONE[spec.category] ?? 'border-l-muted') : 'border-l-danger',
        selected ? 'ring-2 ring-primary' : '',
        // A validation error outranks a live-failure warning, which outranks
        // "this ran in the last dry run" — the first two are things to fix.
        data.broken
          ? 'border-danger'
          : data.hotspot
            ? 'border-amber'
            : traced
              ? 'border-success'
              : 'border-border',
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-2.5 !border-border !bg-surface"
      />

      <div className="min-w-0 flex-1 px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium">{data.title || data.label}</span>
          <span className="flex shrink-0 items-center gap-1">
            {data.hotspot ? <Badge tone="amber">!</Badge> : null}
            {spec?.is_agent ? <Badge tone="primary">AI</Badge> : null}
          </span>
        </div>
        {data.title ? <p className="mt-0.5 truncate text-[11px] text-muted">{data.label}</p> : null}
        <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{data.nodeType}</p>
        {data.summary ? (
          <p className="mt-1 truncate text-[11px] text-muted" title={data.summary}>
            {data.summary}
          </p>
        ) : null}
      </div>

      {ports.length > 0 ? (
        <div className="flex w-16 shrink-0 flex-col justify-around gap-1 border-l border-border py-2">
          {ports.map((port) => (
            <span key={port} className="relative flex items-center justify-end pr-2.5 text-right">
              <span
                className={cn(
                  'truncate text-[10px]',
                  data.tracedPort === port ? 'font-medium text-success' : 'text-muted',
                )}
              >
                {port}
              </span>
              <Handle
                type="source"
                position={Position.Right}
                id={port}
                className="!static !size-2.5 !translate-x-1.5 !transform-none !border-border !bg-surface"
              />
            </span>
          ))}
        </div>
      ) : (
        // Terminal nodes have no output ports, but the canvas-only "结束"
        // anchor still needs a source handle to draw its incoming edge.
        <Handle
          type="source"
          position={Position.Right}
          className="!size-2.5 !border-border !bg-surface"
        />
      )}
    </div>
  );
}
