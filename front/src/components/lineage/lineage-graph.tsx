'use client';

import * as dagre from '@dagrejs/dagre';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo } from 'react';

import { IconTombstone } from '@/components/ui/icons';
import type { Locale } from '@/i18n/routing';
import type { LineageNode, LineageResponse } from '@/lib/api/types';
import { cn } from '@/lib/cn';

const NODE_WIDTH = 168;
const NODE_HEIGHT = 64;

interface GraphNode {
  id: string;
  workId: string;
  title: string;
  author: string;
  tombstone: boolean;
  direction: 'ancestor' | 'root' | 'descendant';
  x: number;
  y: number;
}

interface GraphEdge {
  id: string;
  points: Array<{ x: number; y: number }>;
}

/**
 * Tree view of a work's whole lineage, both directions at once.
 *
 * Layout comes from dagre but the drawing is hand-rolled SVG rather than a
 * graph library: the nodes have to consume the same theme tokens as the rest
 * of the page, and a canvas-based renderer would neither theme nor be
 * reachable by keyboard.
 */
export function LineageGraph({
  lineage,
  selectedVersionId,
  onSelect,
}: {
  lineage: LineageResponse;
  selectedVersionId?: string;
  onSelect: (node: { workVersionId: string; workId: string; title: string }) => void;
}) {
  const t = useTranslations('lineagePanel');
  const tWork = useTranslations('work');
  const locale = useLocale() as Locale;

  const { nodes, edges, width, height } = useMemo(() => layout(lineage), [lineage]);

  return (
    <div className="overflow-auto rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
      <svg
        role="img"
        aria-label={t('title')}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="min-w-full"
      >
        <g>
          {edges.map((edge) => (
            <polyline
              key={edge.id}
              points={edge.points.map((point) => `${point.x},${point.y}`).join(' ')}
              fill="none"
              stroke="var(--border)"
              strokeWidth={1.5}
            />
          ))}
        </g>

        {nodes.map((node) => {
          const selected = node.id === selectedVersionId;
          return (
            <g
              key={node.id}
              transform={`translate(${node.x - NODE_WIDTH / 2}, ${node.y - NODE_HEIGHT / 2})`}
              tabIndex={0}
              role="button"
              aria-label={`${node.title} · ${node.author}`}
              aria-current={selected ? 'true' : undefined}
              className="cursor-pointer outline-none focus-visible:[&>rect]:stroke-[var(--focus)]"
              onClick={() =>
                onSelect({ workVersionId: node.id, workId: node.workId, title: node.title })
              }
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect({ workVersionId: node.id, workId: node.workId, title: node.title });
                }
              }}
            >
              <rect
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx={10}
                fill={node.tombstone ? 'transparent' : 'var(--surface-raised)'}
                stroke={
                  selected
                    ? 'var(--primary)'
                    : node.direction === 'root'
                      ? 'var(--amber)'
                      : 'var(--border)'
                }
                strokeWidth={selected || node.direction === 'root' ? 2 : 1}
                strokeDasharray={node.tombstone ? '4 3' : undefined}
              />
              <text
                x={12}
                y={26}
                fill="var(--text)"
                fontSize={12.5}
                fontWeight={600}
                className={cn(node.tombstone && 'opacity-60')}
              >
                {truncate(node.title, 18)}
              </text>
              <text x={12} y={44} fill="var(--text-muted)" fontSize={11}>
                {node.tombstone ? t('tombstone') : truncate(node.author, 20)}
              </text>
              {node.direction === 'root' ? (
                <text x={NODE_WIDTH - 12} y={26} fill="var(--amber)" fontSize={10} textAnchor="end">
                  {tWork('original')}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>

      <p className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm border-2 border-amber" />
          {t('ancestors')}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm border border-border" />
          {t('descendants')}
        </span>
        <span className="flex items-center gap-1.5">
          <IconTombstone className="size-3.5" />
          {t('tombstoneHint')}
        </span>
        {lineage.truncated ? (
          <span className="tabular">
            {t('truncated', {
              count: new Intl.NumberFormat(locale).format(countNodes(lineage.root)),
            })}
          </span>
        ) : null}
      </p>
    </div>
  );
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function countNodes(node: LineageNode): number {
  return 1 + (node.children ?? []).reduce((sum, child) => sum + countNodes(child), 0);
}

function authorName(author: unknown): string {
  if (author && typeof author === 'object' && 'display_name' in author) {
    return String((author as { display_name: unknown }).display_name);
  }
  return '';
}

function layout(lineage: LineageResponse) {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: 'TB', nodesep: 28, ranksep: 44, marginx: 8, marginy: 8 });
  graph.setDefaultEdgeLabel(() => ({}));

  const meta = new Map<string, Omit<GraphNode, 'x' | 'y'>>();

  const add = (node: Omit<GraphNode, 'x' | 'y'>) => {
    if (meta.has(node.id)) return;
    meta.set(node.id, node);
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  };

  // Ancestors arrive newest-first; walking them oldest-first lets each one
  // point at the next, ending at the work the user is looking at.
  const ancestors = [...(lineage.ancestors ?? [])].sort((a, b) => b.depth - a.depth);
  ancestors.forEach((ancestor, index) => {
    add({
      id: ancestor.work_version_id,
      workId: ancestor.work_id,
      title: ancestor.title,
      author: ancestor.author?.display_name ?? '',
      tombstone: ancestor.is_tombstone,
      direction: index === 0 ? 'root' : 'ancestor',
    });
  });

  const rootId = lineage.root.work_version_id;
  add({
    id: rootId,
    workId: lineage.root.work_id,
    title: lineage.root.title,
    author: authorName(lineage.root.author),
    tombstone: lineage.root.is_tombstone,
    direction: ancestors.length === 0 ? 'root' : 'descendant',
  });

  for (let index = 0; index < ancestors.length; index += 1) {
    const from = ancestors[index]!.work_version_id;
    const to = ancestors[index + 1]?.work_version_id ?? rootId;
    graph.setEdge(from, to);
  }

  const walk = (node: LineageNode) => {
    for (const child of node.children ?? []) {
      add({
        id: child.work_version_id,
        workId: child.work_id,
        title: child.title,
        author: authorName(child.author),
        tombstone: child.is_tombstone,
        direction: 'descendant',
      });
      graph.setEdge(node.work_version_id, child.work_version_id);
      walk(child);
    }
  };
  walk(lineage.root);

  dagre.layout(graph);

  const nodes: GraphNode[] = [];
  for (const [id, info] of meta) {
    const positioned = graph.node(id);
    if (positioned) nodes.push({ ...info, x: positioned.x, y: positioned.y });
  }

  const edges: GraphEdge[] = graph.edges().map((edge) => ({
    id: `${edge.v}->${edge.w}`,
    points: graph.edge(edge).points ?? [],
  }));

  const size = graph.graph();
  return {
    nodes,
    edges,
    width: Math.max(size.width ?? 0, NODE_WIDTH + 16),
    height: Math.max(size.height ?? 0, NODE_HEIGHT + 16),
  };
}
