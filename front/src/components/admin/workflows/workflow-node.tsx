'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';

import { Badge } from '@/components/ui/primitives';
import type { NodeTypeView } from '@/lib/api/admin-types';
import { cn } from '@/lib/cn';

export interface WorkflowNodeData {
  nodeType: string;
  config: Record<string, unknown>;
  spec: NodeTypeView | undefined;
  label: string;
  broken?: boolean;
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
  const summary = summarize(data.config);

  return (
    <div
      className={cn(
        'w-56 rounded-[var(--radius-md)] border border-l-4 bg-surface-raised px-3 py-2.5 shadow-card',
        spec ? CATEGORY_TONE[spec.category] ?? 'border-l-muted' : 'border-l-danger',
        selected ? 'ring-2 ring-primary' : '',
        data.broken ? 'border-danger' : 'border-border',
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!size-2.5 !border-border !bg-surface"
      />

      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium">{data.label}</span>
        {spec?.is_agent ? (
          <Badge tone="primary" className="shrink-0">
            AI
          </Badge>
        ) : null}
      </div>
      <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{data.nodeType}</p>
      {summary ? <p className="mt-1 truncate text-[11px] text-muted">{summary}</p> : null}

      {ports.length > 0 ? (
        <div className="mt-2.5 flex justify-between gap-1 border-t border-border pt-1.5">
          {ports.map((port) => (
            <span key={port} className="relative flex-1 pt-2.5 text-center">
              <span className="truncate text-[10px] text-muted">{port}</span>
              <Handle
                type="source"
                position={Position.Bottom}
                id={port}
                className="!size-2.5 !border-border !bg-surface"
                style={{ left: '50%' }}
              />
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function summarize(config: Record<string, unknown>): string {
  const entries = Object.entries(config).filter(([, value]) => value !== null && value !== undefined);
  if (entries.length === 0) return '';
  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join('/') : String(value)}`)
    .join('  ');
}
