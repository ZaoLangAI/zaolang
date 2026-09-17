import { describe, expect, it } from 'vitest';

import type { CanvasGraph } from './api';
import { offsetGraph, parseCanvasFile, serializeCanvas } from './canvas-io';

const graph: CanvasGraph = {
  nodes: [
    { id: 'cnd_a', kind: 'note', position: { x: 10, y: 20 }, data: { label: '想法' } },
    {
      id: 'cnd_b',
      kind: 'image',
      position: { x: 300, y: 20 },
      binding: { kind: 'image', asset_id: 'ast_1' },
      data: { label: '参考' },
    },
  ],
  edges: [{ id: 'cne_1', source: 'cnd_a', target: 'cnd_b', kind: 'link' }],
};

describe('canvas export / import', () => {
  it('round-trips the arrangement', () => {
    const restored = parseCanvasFile(serializeCanvas('我的画布', graph));
    expect(restored.nodes).toHaveLength(2);
    expect(restored.nodes.map((n) => n.kind)).toEqual(['note', 'image']);
    expect(restored.nodes.map((n) => n.data?.label)).toEqual(['想法', '参考']);
    expect(restored.nodes.map((n) => n.position)).toEqual([
      { x: 10, y: 20 },
      { x: 300, y: 20 },
    ]);
  });

  it('mints fresh ids so a file can be imported into its own canvas', () => {
    const restored = parseCanvasFile(serializeCanvas('t', graph));
    const ids = restored.nodes.map((n) => n.id);
    expect(ids).not.toContain('cnd_a');
    expect(ids).not.toContain('cnd_b');
    expect(new Set(ids).size).toBe(2);
  });

  it('rewires edges onto the new ids rather than dropping them', () => {
    const restored = parseCanvasFile(serializeCanvas('t', graph));
    expect(restored.edges).toHaveLength(1);
    const [edge] = restored.edges;
    expect(edge!.source).toBe(restored.nodes[0]!.id);
    expect(edge!.target).toBe(restored.nodes[1]!.id);
    expect(edge!.id).not.toBe('cne_1');
  });

  it('drops domain bindings — they belong to whoever exported the file', () => {
    const restored = parseCanvasFile(serializeCanvas('t', graph));
    expect(restored.nodes.every((n) => n.binding === undefined)).toBe(true);
  });

  it('rejects a file that is not a canvas export', () => {
    expect(() => parseCanvasFile('not json')).toThrow('invalid-json');
    expect(() => parseCanvasFile('{"hello":1}')).toThrow('invalid-shape');
    expect(() => parseCanvasFile('{"graph":{"nodes":[],"edges":[]}}')).toThrow('empty');
  });

  it('skips malformed nodes instead of failing the whole import', () => {
    const messy = JSON.stringify({
      graph: { nodes: [{ id: 'x', kind: 'note' }, { nope: true }, 42], edges: [] },
    });
    expect(parseCanvasFile(messy).nodes).toHaveLength(1);
  });

  it('drops an edge whose endpoints did not survive', () => {
    const messy = JSON.stringify({
      graph: {
        nodes: [{ id: 'x', kind: 'note', position: { x: 0, y: 0 } }],
        edges: [{ id: 'e', source: 'x', target: 'gone' }],
      },
    });
    expect(parseCanvasFile(messy).edges).toEqual([]);
  });
});

describe('offsetGraph', () => {
  it('shifts every node so an import lands beside what is already there', () => {
    const moved = offsetGraph(graph, 40, 40);
    expect(moved.nodes.map((n) => n.position)).toEqual([
      { x: 50, y: 60 },
      { x: 340, y: 60 },
    ]);
    expect(moved.edges).toBe(graph.edges);
  });
});
