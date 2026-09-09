import { describe, expect, it } from 'vitest';

import type { CanvasChange, CanvasGraph, CanvasNode } from './api';
import { applyChanges, diffGraph } from './graph-ops';

function node(id: string, overrides: Partial<CanvasNode> = {}): CanvasNode {
  return {
    id,
    kind: 'note',
    position: { x: 0, y: 0 },
    data: {},
    revision: 1,
    origin: 'user',
    ...overrides,
  };
}

function graph(nodes: CanvasNode[], edges: CanvasGraph['edges'] = []): CanvasGraph {
  return { nodes, edges };
}

describe('diffGraph', () => {
  it('emits nothing when the arrangement is unchanged', () => {
    const same = graph([node('a')]);
    expect(diffGraph(same, same)).toEqual([]);
  });

  it('treats a sub-pixel drag that rounds to the same spot as no change', () => {
    // The server stores integers. Sending a round trip for a move nobody can
    // see would make every mouse tremor cost a request.
    const base = graph([node('a', { position: { x: 10, y: 10 } })]);
    const next = graph([node('a', { position: { x: 10.4, y: 9.7 } })]);
    expect(diffGraph(base, next)).toEqual([]);
  });

  it('creates a card the server has never seen', () => {
    const ops = diffGraph(graph([]), graph([node('a')]));
    expect(ops).toHaveLength(1);
    expect(ops[0]!.kind).toBe('node.create');
  });

  it('sends only the fields that moved', () => {
    const base = graph([node('a', { position: { x: 0, y: 0 }, data: { label: '保留我' } })]);
    const next = graph([node('a', { position: { x: 50, y: 20 }, data: { label: '保留我' } })]);
    const ops = diffGraph(base, next);
    expect(ops).toHaveLength(1);
    const op = ops[0]!;
    expect(op.kind).toBe('node.update');
    if (op.kind !== 'node.update') throw new Error('unreachable');
    expect(op.position).toEqual({ x: 50, y: 20 });
    // An omitted field is left alone server-side; sending `data` here would
    // be a needless write of text that did not change.
    expect(op.data).toBeUndefined();
    expect(op.size).toBeUndefined();
  });

  it('quotes the card revision it last saw, which is the compare-and-set token', () => {
    const base = graph([node('a', { revision: 7 })]);
    const next = graph([node('a', { revision: 7, position: { x: 1, y: 1 } })]);
    const op = diffGraph(base, next)[0]!;
    if (op.kind !== 'node.update') throw new Error('expected an update');
    expect(op.expected_revision).toBe(7);
  });

  it('deletes a card that is gone, quoting its revision', () => {
    const ops = diffGraph(graph([node('a', { revision: 3 })]), graph([]));
    expect(ops).toHaveLength(1);
    const op = ops[0]!;
    if (op.kind !== 'node.delete') throw new Error('expected a delete');
    expect(op.node_id).toBe('a');
    expect(op.expected_revision).toBe(3);
  });

  it('orders edge deletes before node deletes', () => {
    // So a partially-applied batch never describes a graph where an edge
    // outlives one of its endpoints.
    const base = graph([node('a'), node('b')], [{ id: 'e1', source: 'a', target: 'b' }]);
    const ops = diffGraph(base, graph([node('b')]));
    const kinds = ops.map((op) => op.kind);
    expect(kinds.indexOf('edge.delete')).toBeLessThan(kinds.indexOf('node.delete'));
  });

  it('orders creates before the updates and deletes in the same batch', () => {
    const base = graph([node('old', { revision: 2 }), node('gone')]);
    const next = graph([node('old', { revision: 2, position: { x: 9, y: 9 } }), node('fresh')]);
    const kinds = diffGraph(base, next).map((op) => op.kind);
    expect(kinds[0]).toBe('node.create');
    expect(kinds.indexOf('node.update')).toBeLessThan(kinds.indexOf('node.delete'));
  });

  it('notices a binding appearing on a card', () => {
    const base = graph([node('a')]);
    const next = graph([node('a', { binding: { kind: 'image', asset_id: 'ast_1' } })]);
    const op = diffGraph(base, next)[0]!;
    if (op.kind !== 'node.update') throw new Error('expected an update');
    expect(op.binding).toEqual({ kind: 'image', asset_id: 'ast_1' });
  });

  it('gives every op a distinct id, so a queued flush can be reconciled', () => {
    const ops = diffGraph(graph([]), graph([node('a'), node('b'), node('c')]));
    expect(new Set(ops.map((op) => op.op_id)).size).toBe(3);
  });
});

function change(overrides: Partial<CanvasChange>): CanvasChange {
  return {
    seq: 1,
    entity_type: 'node',
    entity_id: 'a',
    action: 'created',
    actor: 'user',
    payload: {},
    ...overrides,
  };
}

describe('applyChanges', () => {
  it('returns the same graph when there is nothing to apply', () => {
    const base = graph([node('a')]);
    expect(applyChanges(base, [])).toBe(base);
  });

  it('adds a card another session created', () => {
    const result = applyChanges(graph([]), [
      change({
        entity_id: 'srv',
        payload: { id: 'srv', kind: 'image', position: { x: 5, y: 5 }, revision: 1 },
      }),
    ]);
    expect(result.nodes.map((n) => n.id)).toEqual(['srv']);
  });

  it('replaces the optimistic local copy with the server row', () => {
    // This is how a client learns the revision it must quote next; keeping the
    // local copy would make its next update conflict every time.
    const base = graph([node('a', { revision: 1, position: { x: 0, y: 0 } })]);
    const result = applyChanges(base, [
      change({
        action: 'updated',
        payload: { id: 'a', kind: 'note', position: { x: 80, y: 0 }, revision: 2 },
      }),
    ]);
    expect(result.nodes[0]!.revision).toBe(2);
    expect(result.nodes[0]!.position).toEqual({ x: 80, y: 0 });
  });

  it('marks an agent-created card as such', () => {
    const result = applyChanges(graph([]), [
      change({
        actor: 'agent',
        entity_id: 'gen',
        payload: {
          id: 'gen',
          kind: 'image',
          position: { x: 0, y: 0 },
          origin: 'agent',
          revision: 1,
        },
      }),
    ]);
    expect(result.nodes[0]!.origin).toBe('agent');
  });

  it('drops a deleted card along with the edges touching it', () => {
    // The server logs the cascaded edges too, but a client that has the node
    // and not those entries would keep drawing lines into nothing — so the
    // fold has to be total on its own.
    const base = graph(
      [node('a'), node('b')],
      [
        { id: 'e1', source: 'a', target: 'b' },
        { id: 'e2', source: 'b', target: 'a' },
      ],
    );
    const result = applyChanges(base, [change({ action: 'deleted', entity_id: 'a', payload: {} })]);
    expect(result.nodes.map((n) => n.id)).toEqual(['b']);
    expect(result.edges).toEqual([]);
  });

  it('ignores agent-run entries, which are not graph entities', () => {
    const base = graph([node('a')]);
    const result = applyChanges(base, [
      change({ entity_type: 'agent_run', entity_id: 'car_1', payload: { status: 'running' } }),
    ]);
    expect(result.nodes.map((n) => n.id)).toEqual(['a']);
  });

  it('applies changes in order, so the last write wins', () => {
    const result = applyChanges(graph([node('a', { revision: 1 })]), [
      change({
        seq: 2,
        action: 'updated',
        payload: { id: 'a', kind: 'note', position: { x: 1, y: 1 }, revision: 2 },
      }),
      change({
        seq: 3,
        action: 'updated',
        payload: { id: 'a', kind: 'note', position: { x: 2, y: 2 }, revision: 3 },
      }),
    ]);
    expect(result.nodes[0]!.revision).toBe(3);
    expect(result.nodes[0]!.position).toEqual({ x: 2, y: 2 });
  });
});

describe('the round trip', () => {
  it('a diff applied through the server feed converges on the desired graph', () => {
    // The property the sync loop depends on: send ops, fold the resulting
    // changes back, and the client's base equals what the server now holds.
    const base = graph([node('keep', { revision: 4 })]);
    const desired = graph([
      node('keep', { revision: 4, position: { x: 30, y: 0 } }),
      node('added'),
    ]);
    const ops = diffGraph(base, desired);
    expect(ops.map((op) => op.kind).sort()).toEqual(['node.create', 'node.update']);

    const settled = applyChanges(desired, [
      change({
        seq: 1,
        entity_id: 'added',
        payload: { id: 'added', kind: 'note', position: { x: 0, y: 0 }, revision: 1 },
      }),
      change({
        seq: 2,
        entity_id: 'keep',
        action: 'updated',
        payload: { id: 'keep', kind: 'note', position: { x: 30, y: 0 }, revision: 5 },
      }),
    ]);
    const byId = new Map(settled.nodes.map((n) => [n.id, n]));
    expect(byId.get('keep')!.revision).toBe(5);
    expect(byId.get('added')!.revision).toBe(1);
    // A second diff against the settled base has nothing left to send.
    expect(diffGraph(settled, settled)).toEqual([]);
  });
});
