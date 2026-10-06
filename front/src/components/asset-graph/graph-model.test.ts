import { describe, expect, it } from 'vitest';

import type { AssetEdge, AssetEntry, AssetGraph, AssetVariant } from '@/lib/api/types';

import {
  attributeRows,
  buildGraph,
  childPosition,
  ENTRY_COLUMNS,
  LOOK_WIDTH,
  lookSize,
  outlineOrder,
  parseNodeId,
} from './graph-model';
import { layoutGraph } from './layout';
import { versionIndex } from './versions';

const entry = (id: string, status: 'approved' | 'candidate' = 'approved') =>
  ({ id, asset_id: id, entry_type: 'other', status, url: `https://cdn/${id}.png` }) as AssetEntry;

const look = (id: string, entries: AssetEntry[] = [], extra: Partial<AssetVariant> = {}) =>
  ({
    id,
    name: id,
    is_default: id === 'default',
    sort_order: 0,
    presets: {},
    attributes: { custom: [] },
    entries,
    ...extra,
  }) as AssetVariant;

const edge = (id: string, level: 'variant' | 'entry', source: string, target: string) =>
  ({
    id,
    level,
    source_id: source,
    target_id: target,
    relations: ['age'],
    origin: 'manual',
  }) as AssetEdge;

function graph(variants: AssetVariant[], edges: AssetEdge[] = []): AssetGraph {
  return {
    card_id: 'sk_1',
    card_kind: 'character',
    name: '林夏',
    variants,
    edges,
    pending: [],
    caps: { max_variants: 48, max_entries_per_variant: 24, max_entries: 480, max_edges: 2000 },
  } as AssetGraph;
}

const noop = () => undefined;

describe('attributeRows', () => {
  it('lists set attributes in a fixed order, custom rows last', () => {
    const variant = look('old', [], {
      presets: { period: 'republic', age_stage: 'elderly' },
      attributes: { outfit: '长衫', custom: [{ key: '身份', value: '卧底' }] },
    });
    expect(attributeRows(variant, 'character').map((row) => row.key)).toEqual([
      'age_stage',
      'period',
      'outfit',
      'custom',
    ]);
  });

  it("shows a prop variant's condition and period", () => {
    const variant = look('worn', [], {
      presets: { prop_state: 'worn', period: 'ancient', lighting: 'dusk' },
    });
    expect(attributeRows(variant, 'prop').map((row) => [row.key, row.value])).toEqual([
      ['prop_state', 'worn'],
      ['period', 'ancient'],
    ]);
  });
});

describe('lookSize / childPosition', () => {
  it('grows an expanded look to fit a grid of its images', () => {
    const variant = look('a', [entry('1'), entry('2'), entry('3'), entry('4')]);
    const collapsed = lookSize(variant, 'character', false);
    const expanded = lookSize(variant, 'character', true);
    expect(collapsed.width).toBe(LOOK_WIDTH);
    expect(expanded.width).toBeGreaterThanOrEqual(LOOK_WIDTH);
    expect(expanded.height).toBeGreaterThan(collapsed.height - 72);
    // The 4th image starts the second row.
    expect(childPosition(variant, 'character', ENTRY_COLUMNS).x).toBe(
      childPosition(variant, 'character', 0).x,
    );
    expect(childPosition(variant, 'character', ENTRY_COLUMNS).y).toBeGreaterThan(
      childPosition(variant, 'character', 0).y,
    );
  });
});

describe('buildGraph', () => {
  const young = look('young', [entry('y1'), entry('y2', 'candidate')]);
  const old = look('old', [entry('o1')]);
  const data = graph(
    [look('default'), young, old],
    [
      edge('e1', 'variant', 'young', 'old'),
      edge('e2', 'entry', 'y1', 'o1'),
      edge('e3', 'entry', 'y2', 'o1'),
    ],
  );

  it('draws only looks while everything is collapsed, folding image edges into one hint', () => {
    const built = buildGraph(data, {
      expanded: new Set(),
      selection: { type: 'card' },
      onToggle: noop,
    });
    expect(built.nodes.map((n) => n.id)).toEqual(['v:default', 'v:young', 'v:old']);
    const hint = built.edges.find((e) => e.id.startsWith('hint:'));
    expect(hint?.source).toBe('v:young');
    expect(hint?.data?.count).toBe(2);
    expect(built.edges.find((e) => e.id === 'e1')?.source).toBe('v:young');
  });

  it('adds image children and image edges once both ends are expanded', () => {
    const built = buildGraph(data, {
      expanded: new Set(['young', 'old']),
      selection: { type: 'entry', id: 'y1' },
      onToggle: noop,
    });
    const child = built.nodes.find((n) => n.id === 'e:y1');
    expect(child?.parentId).toBe('v:young');
    expect(child?.selected).toBe(true);
    expect(built.edges.find((e) => e.id === 'e2')).toMatchObject({
      source: 'e:y1',
      target: 'e:o1',
    });
    expect(built.edges.some((e) => e.id.startsWith('hint:'))).toBe(false);
    // Parents precede their children (React Flow requires it).
    const ids = built.nodes.map((n) => n.id);
    expect(ids.indexOf('v:young')).toBeLessThan(ids.indexOf('e:y1'));
  });

  it('puts a pending job inside its target look', () => {
    const withJob = {
      ...data,
      pending: [{ job_id: 'job_1', status: 'running', target_variant_id: 'old' }],
    } as AssetGraph;
    const built = buildGraph(withJob, {
      expanded: new Set(['old']),
      selection: { type: 'card' },
      onToggle: noop,
    });
    expect(built.nodes.find((n) => n.id === 'p:job_1')?.parentId).toBe('v:old');
    const collapsed = buildGraph(withJob, {
      expanded: new Set(),
      selection: { type: 'card' },
      onToggle: noop,
    });
    const node = collapsed.nodes.find((n) => n.id === 'v:old');
    expect(node?.type === 'look' && node.data.pendingCount).toBe(1);
  });
});

describe('layoutGraph', () => {
  it('places a derived look right of its source, deterministically', () => {
    const data = graph(
      [look('default'), look('young'), look('old')],
      [edge('e1', 'variant', 'young', 'old')],
    );
    const built = buildGraph(data, {
      expanded: new Set(),
      selection: { type: 'card' },
      onToggle: noop,
    });
    const first = layoutGraph(built);
    const again = layoutGraph(built);
    const x = (id: string) => first.find((n) => n.id === id)!.position.x;
    expect(x('v:old')).toBeGreaterThan(x('v:young'));
    expect(again.map((n) => n.position)).toEqual(first.map((n) => n.position));
  });

  it('keeps a look the author dragged where they put it', () => {
    const data = graph([look('default'), look('young')]);
    const built = buildGraph(data, {
      expanded: new Set(),
      selection: { type: 'card' },
      onToggle: noop,
    });
    const placed = layoutGraph(built, { 'v:young': { x: 900, y: 40 } });
    expect(placed.find((n) => n.id === 'v:young')?.position).toEqual({ x: 900, y: 40 });
  });
});

describe('outlineOrder / parseNodeId', () => {
  it('orders looks by derivation depth and records parents', () => {
    const data = graph(
      [look('default'), look('old'), look('young')],
      [edge('e1', 'variant', 'young', 'old')],
    );
    expect(outlineOrder(data).map((row) => [row.variant.id, row.depth, row.parents])).toEqual([
      ['default', 0, []],
      ['young', 0, []],
      ['old', 1, ['young']],
    ]);
  });

  it('parses node ids', () => {
    expect(parseNodeId('v:skv_1')).toEqual({ kind: 'variant', id: 'skv_1' });
    expect(parseNodeId('e:ske_1')).toEqual({ kind: 'entry', id: 'ske_1' });
    expect(parseNodeId('x:1')).toBeNull();
  });
});

describe('versions', () => {
  it('folds an edited image and same-slot candidates into one node', () => {
    const sheet = { ...entry('sheet'), entry_type: 'character_sheet' } as AssetEntry;
    const regenerated = {
      ...entry('regen', 'candidate'),
      entry_type: 'character_sheet',
      created_at: '2026-10-05T02:00:00Z',
    } as AssetEntry;
    const pose = { ...entry('pose'), entry_type: 'pose' } as AssetEntry;
    const poseEdit = {
      ...entry('pose2', 'candidate'),
      entry_type: 'pose',
      created_at: '2026-10-05T03:00:00Z',
    } as AssetEntry;
    const old = { ...entry('old'), entry_type: 'character_sheet' } as AssetEntry;
    const data = graph(
      [look('default', [sheet, regenerated, pose, poseEdit]), look('old', [old])],
      [
        { ...edge('ed', 'entry', 'pose', 'pose2'), relations: ['edit'] } as AssetEdge,
        edge('d1', 'entry', 'regen', 'old'),
      ],
    );
    const { headOf, versions } = versionIndex(data);
    expect(headOf.get('regen')).toBe('sheet');
    expect(headOf.get('pose2')).toBe('pose');
    expect(versions.get('sheet')?.map((e) => e.id)).toEqual(['sheet', 'regen']);

    const built = buildGraph(
      {
        ...data,
        pending: [{ job_id: 'j', status: 'running', mode: 'edit', source_entry_id: 'pose2' }],
      } as AssetGraph,
      {
        expanded: new Set(['default', 'old']),
        selection: { type: 'entry', id: 'regen' },
        onToggle: noop,
      },
    );
    const entryNodes = built.nodes.filter((n) => n.type === 'entry');
    expect(entryNodes.map((n) => n.id)).toEqual(['e:sheet', 'e:pose', 'e:old']);
    const sheetNode = entryNodes.find((n) => n.id === 'e:sheet');
    expect(sheetNode?.selected).toBe(true);
    expect(sheetNode?.type === 'entry' && sheetNode.data.versionCount).toBe(2);
    const poseNode = entryNodes.find((n) => n.id === 'e:pose');
    expect(poseNode?.type === 'entry' && poseNode.data.pendingVersions).toBe(1);
    // No pending node for an edit; the edit edge is not drawn; the derive
    // edge from a version attaches to its head.
    expect(built.nodes.some((n) => n.type === 'pending')).toBe(false);
    expect(built.edges.map((e) => [e.source, e.target])).toEqual([['e:sheet', 'e:old']]);
  });
});
