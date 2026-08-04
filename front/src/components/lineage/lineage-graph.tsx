'use client';

import * as dagre from '@dagrejs/dagre';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useId, useMemo, useRef } from 'react';

import { IconArrowRight, IconTombstone } from '@/components/ui/icons';
import type { Locale } from '@/i18n/routing';
import type { LineageNode, LineageResponse } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { loadAnime, useIsomorphicLayoutEffect, useReducedMotion } from '@/lib/motion';

const EDGE_DRAW_DURATION = 480;
const NODE_FADE_DURATION = 380;

const NODE_WIDTH = 212;
const NODE_HEIGHT = 76;
const THUMB_SIZE = 56;
const THUMB_INSET = 10;
const TEXT_X = THUMB_INSET * 2 + THUMB_SIZE;

interface GraphNode {
  id: string;
  workId: string;
  title: string;
  author: string;
  coverUrl?: string | null;
  tombstone: boolean;
  direction: 'ancestor' | 'root' | 'descendant';
  /** The work the reader opened the graph from. */
  current: boolean;
  x: number;
  y: number;
}

interface GraphEdge {
  id: string;
  from: string;
  to: string;
}

/**
 * Tree view of a work's whole lineage, both directions at once.
 *
 * Laid out left to right: time runs the way the language does, so the original
 * sits at the left edge and every remix grows to its right. Layout comes from
 * dagre but the drawing is hand-rolled SVG rather than a graph library — the
 * nodes have to consume the same theme tokens as the rest of the page, and a
 * canvas-based renderer would neither theme nor be reachable by keyboard.
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
  const arrowId = `${useId()}-arrow`;
  const clipId = `${useId()}-thumb`;

  const { nodes, edges, width, height } = useMemo(() => layout(lineage), [lineage]);
  const positions = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  const reduced = useReducedMotion();
  const pathRefs = useRef(new Map<string, SVGPathElement>());
  const nodeRefs = useRef(new Map<string, SVGGElement>());
  // Nodes are re-created (fresh DOM elements) whenever the graph reshapes, so
  // this fingerprint is exactly "did the set of things to reveal change" —
  // reselecting a node in the same graph must not replay the whole entrance.
  const graphSignature = `${lineage.root.work_version_id}:${nodes.length}:${edges.length}`;

  // Runs before paint: without this, every node would flash fully visible
  // for a frame before the animation effect (which waits on `loadAnime()`)
  // gets a chance to hide them again.
  useIsomorphicLayoutEffect(() => {
    if (reduced) return;
    for (const node of nodeRefs.current.values()) node.style.opacity = '0';
  }, [graphSignature, reduced]);

  useEffect(() => {
    if (reduced) return;
    const paths = Array.from(pathRefs.current.values());
    const groups = Array.from(nodeRefs.current.values());

    loadAnime().then(({ animate, stagger, createDrawable }) => {
      if (paths.length > 0) {
        animate(createDrawable(paths), {
          draw: ['0 0', '0 1'],
          duration: EDGE_DRAW_DURATION,
          delay: stagger(70),
          ease: 'inOutQuad',
        });
      }
      if (groups.length > 0) {
        animate(groups, {
          opacity: [0, 1],
          duration: NODE_FADE_DURATION,
          delay: stagger(45, { start: 90 }),
          ease: 'outQuad',
        });
      }
    });
    // `graphSignature` is the intentional dependency; `nodes`/`edges` are
    // recomputed every render and would otherwise replay this on every one.
  }, [graphSignature, reduced]);

  return (
    <div className="rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
      <p className="mb-3 flex items-center gap-2 text-[11px] text-muted">
        <span>{t('ancestors')}</span>
        <IconArrowRight className="size-3.5" aria-hidden="true" />
        <span>{t('descendants')}</span>
      </p>

      <div className="overflow-auto">
        <svg
          role="img"
          aria-label={t('title')}
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
        >
          <defs>
            <marker
              id={arrowId}
              viewBox="0 0 8 8"
              refX={7}
              refY={4}
              markerWidth={7}
              markerHeight={7}
              orient="auto-start-reverse"
            >
              <path d="M0 0 L8 4 L0 8 z" fill="var(--border-strong)" />
            </marker>
            <clipPath id={clipId}>
              <rect width={THUMB_SIZE} height={THUMB_SIZE} rx={8} />
            </clipPath>
          </defs>

          <g>
            {edges.map((edge) => {
              const from = positions.get(edge.from);
              const to = positions.get(edge.to);
              if (!from || !to) return null;
              return (
                <path
                  key={edge.id}
                  ref={(el) => {
                    if (el) pathRefs.current.set(edge.id, el);
                    else pathRefs.current.delete(edge.id);
                  }}
                  d={edgePath(from, to)}
                  fill="none"
                  stroke="var(--border-strong)"
                  strokeWidth={1.5}
                  markerEnd={`url(#${arrowId})`}
                />
              );
            })}
          </g>

          {nodes.map((node) => {
            const selected = node.id === selectedVersionId;
            const accented = selected || node.current || node.direction === 'root';
            return (
              <g
                key={node.id}
                ref={(el) => {
                  if (el) nodeRefs.current.set(node.id, el);
                  else nodeRefs.current.delete(node.id);
                }}
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
                {selected ? (
                  <rect
                    x={-4}
                    y={-4}
                    width={NODE_WIDTH + 8}
                    height={NODE_HEIGHT + 8}
                    rx={14}
                    fill="none"
                    stroke="var(--primary)"
                    strokeOpacity={0.35}
                    strokeWidth={2}
                  />
                ) : null}

                <rect
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={12}
                  fill={node.tombstone ? 'transparent' : 'var(--surface-raised)'}
                  stroke={
                    selected || node.current
                      ? 'var(--primary)'
                      : node.direction === 'root'
                        ? 'var(--amber)'
                        : 'var(--border)'
                  }
                  strokeWidth={accented ? 2 : 1}
                  strokeDasharray={node.tombstone ? '4 3' : undefined}
                />

                {node.tombstone ? (
                  <g
                    transform={`translate(${THUMB_INSET + THUMB_SIZE / 2 - 9}, ${NODE_HEIGHT / 2 - 9})`}
                  >
                    <IconTombstone width={18} height={18} className="text-muted" />
                  </g>
                ) : (
                  <g transform={`translate(${THUMB_INSET}, ${(NODE_HEIGHT - THUMB_SIZE) / 2})`}>
                    <rect
                      width={THUMB_SIZE}
                      height={THUMB_SIZE}
                      rx={8}
                      fill="var(--surface-soft)"
                    />
                    {node.coverUrl ? (
                      <image
                        href={node.coverUrl}
                        width={THUMB_SIZE}
                        height={THUMB_SIZE}
                        clipPath={`url(#${clipId})`}
                        preserveAspectRatio="xMidYMid slice"
                      />
                    ) : null}
                  </g>
                )}

                <text
                  x={TEXT_X}
                  y={30}
                  fill="var(--text)"
                  fontSize={12.5}
                  fontWeight={600}
                  className={cn(node.tombstone && 'opacity-60')}
                >
                  {truncate(node.title, 12)}
                </text>
                <text x={TEXT_X} y={48} fill="var(--text-muted)" fontSize={11}>
                  {node.tombstone ? t('tombstone') : truncate(node.author, 14)}
                </text>
                {node.direction === 'root' || node.current ? (
                  <text
                    x={NODE_WIDTH - THUMB_INSET}
                    y={NODE_HEIGHT - 12}
                    fill={node.current ? 'var(--primary)' : 'var(--amber)'}
                    fontSize={10}
                    textAnchor="end"
                  >
                    {node.current ? t('currentWork') : tWork('original')}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>

      <p className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm border-2 border-amber" />
          {tWork('original')}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm border-2 border-primary" />
          {t('currentWork')}
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

/**
 * Horizontal S-curve between two node centres.
 *
 * Drawn from the node boxes rather than from dagre's polyline points: the curve
 * has to start on the parent's right edge and land on the child's left edge for
 * the arrow head to read as direction, and dagre's points are routed for
 * straight segments.
 */
function edgePath(from: { x: number; y: number }, to: { x: number; y: number }): string {
  const startX = from.x + NODE_WIDTH / 2;
  const endX = to.x - NODE_WIDTH / 2;
  const bend = Math.max((endX - startX) / 2, 12);
  return `M ${startX} ${from.y} C ${startX + bend} ${from.y}, ${endX - bend} ${to.y}, ${endX} ${to.y}`;
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
  graph.setGraph({ rankdir: 'LR', nodesep: 22, ranksep: 64, marginx: 12, marginy: 12 });
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
      coverUrl: ancestor.cover_url,
      tombstone: ancestor.is_tombstone,
      direction: index === 0 ? 'root' : 'ancestor',
      current: false,
    });
  });

  const rootId = lineage.root.work_version_id;
  add({
    id: rootId,
    workId: lineage.root.work_id,
    title: lineage.root.title,
    author: authorName(lineage.root.author),
    coverUrl: lineage.root.cover_url,
    tombstone: lineage.root.is_tombstone,
    direction: ancestors.length === 0 ? 'root' : 'descendant',
    current: true,
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
        coverUrl: child.cover_url,
        tombstone: child.is_tombstone,
        direction: 'descendant',
        current: false,
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
    from: edge.v,
    to: edge.w,
  }));

  const size = graph.graph();
  return {
    nodes,
    edges,
    width: Math.max(size.width ?? 0, NODE_WIDTH + 24),
    height: Math.max(size.height ?? 0, NODE_HEIGHT + 24),
  };
}
