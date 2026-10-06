import { describe, expect, it } from 'vitest';

import type { CanvasGraph, CanvasSnapshot, CanvasSnapshotEpisode } from './api';
import { flowToGraph, graphToFlow, missingDomainNodes, shotKeysOf } from './graph-convert';

const emptySnapshot: CanvasSnapshot = {
  series: null,
  episodes: [],
  content_links: [],
  skills: [],
  assets: {},
};

function script(scenes: { heading: string; breakpoints: number }[]) {
  return {
    title: 't',
    characters: [],
    scenes: scenes.map((scene) => ({
      heading: scene.heading,
      ref_id: null,
      blocks: [
        { type: 'action', character: null, text: 'x' },
        ...Array.from({ length: scene.breakpoints }, () => ({
          type: 'breakpoint',
          character: null,
          text: '',
        })),
      ],
    })),
  };
}

function snapshotWith(overrides: Partial<CanvasSnapshot>): CanvasSnapshot {
  return { ...emptySnapshot, ...overrides };
}

describe('shotKeysOf', () => {
  it('numbers breakpoints per scene, matching the script studio ordinal rule', () => {
    expect(shotKeysOf(script([{ heading: '场景一', breakpoints: 2 }]))).toEqual([
      '场景一#0',
      '场景一#1',
    ]);
  });

  it('restarts the ordinal in each scene', () => {
    expect(
      shotKeysOf(
        script([
          { heading: '场景一', breakpoints: 1 },
          { heading: '场景二', breakpoints: 1 },
        ]),
      ),
    ).toEqual(['场景一#0', '场景二#0']);
  });

  it('treats a missing or malformed script as having no shots', () => {
    expect(shotKeysOf(null)).toEqual([]);
    expect(shotKeysOf({ scenes: 'nope' })).toEqual([]);
  });
});

describe('graphToFlow stale detection', () => {
  const graph: CanvasGraph = {
    nodes: [
      {
        id: 'cnd_1',
        kind: 'shot',
        position: { x: 0, y: 0 },
        binding: { kind: 'shot', episode_id: 'dep_1', breakpoint_key: '场景一#0' },
        data: { label: '第一个镜头' },
      },
    ],
    edges: [],
  };

  const episode: CanvasSnapshotEpisode = {
    id: 'dep_1',
    season_number: 1,
    episode_number: 1,
    episode_kind: 'main',
    title: '第一集',
    synopsis: null,
    status: 'draft',
    canonical_work_id: null,
    script: script([{ heading: '场景一', breakpoints: 1 }]),
  };
  const live = snapshotWith({ episodes: [episode] });

  it('keeps a shot node live while its breakpoint still exists', () => {
    const { nodes } = graphToFlow(graph, live);
    expect(nodes[0]!.data.stale).toBe(false);
  });

  it('marks the node stale — but keeps it — when a scene is renamed', () => {
    const renamed = snapshotWith({
      episodes: [{ ...episode, script: script([{ heading: '场景零', breakpoints: 1 }]) }],
    });
    const { nodes } = graphToFlow(graph, renamed);
    expect(nodes).toHaveLength(1);
    expect(nodes[0]!.data.stale).toBe(true);
    // The last known label survives, so a stale card is still identifiable.
    expect(nodes[0]!.data.label).toBe('第一个镜头');
  });

  it('marks the node stale when its episode is gone entirely', () => {
    const { nodes } = graphToFlow(graph, emptySnapshot);
    expect(nodes[0]!.data.stale).toBe(true);
  });

  it('never marks an unbound card stale', () => {
    const notes: CanvasGraph = {
      nodes: [{ id: 'cnd_n', kind: 'note', position: { x: 0, y: 0 }, data: { label: '想法' } }],
      edges: [],
    };
    const { nodes } = graphToFlow(notes, emptySnapshot);
    expect(nodes[0]!.data.stale).toBe(false);
  });

  it('drops edges whose endpoints no longer exist rather than rendering them', () => {
    const dangling: CanvasGraph = {
      nodes: [{ id: 'cnd_a', kind: 'note', position: { x: 0, y: 0 } }],
      edges: [{ id: 'cne_1', source: 'cnd_a', target: 'cnd_ghost' }],
    };
    const { edges } = graphToFlow(dangling, emptySnapshot);
    expect(edges).toEqual([]);
  });
});

describe('flowToGraph', () => {
  it('round-trips positions and bindings', () => {
    const graph: CanvasGraph = {
      nodes: [
        {
          id: 'cnd_1',
          kind: 'episode',
          position: { x: 12.4, y: 40.6 },
          binding: { kind: 'episode', episode_id: 'dep_1' },
          data: { label: '第一集' },
        },
      ],
      edges: [],
    };
    const snapshot = snapshotWith({
      episodes: [
        {
          id: 'dep_1',
          season_number: 1,
          episode_number: 1,
          episode_kind: 'main',
          title: '第一集',
          synopsis: null,
          status: 'draft',
          canonical_work_id: null,
          script: null,
        },
      ],
    });
    const { nodes, edges } = graphToFlow(graph, snapshot);
    const back = flowToGraph(nodes, edges);
    expect(back.nodes[0]!.binding).toEqual({ kind: 'episode', episode_id: 'dep_1' });
    // Positions are rounded so a sub-pixel drag doesn't churn the payload.
    expect(back.nodes[0]!.position).toEqual({ x: 12, y: 41 });
  });
});

describe('missingDomainNodes', () => {
  const snapshot = snapshotWith({
    series: {
      id: 'ser_1',
      title: '我的短剧',
      english_title: null,
      status: 'active',
      planned_episode_count: null,
      genre_tags: [],
      target_platforms: [],
      logo_url: null,
    },
    episodes: [
      {
        id: 'dep_1',
        season_number: 1,
        episode_number: 1,
        episode_kind: 'main',
        title: '第一集',
        synopsis: null,
        status: 'draft',
        canonical_work_id: null,
        script: null,
      },
    ],
  });

  it('seeds a node for the series and each episode on a fresh canvas', () => {
    const added = missingDomainNodes({ nodes: [], edges: [] }, snapshot);
    expect(added.map((n) => n.kind)).toEqual(['series', 'episode']);
  });

  it('seeds a clip node for a draft generated elsewhere', () => {
    // This is what closes the generation loop: the studio links the draft to
    // the episode server-side, and the canvas picks it up on the next load
    // without the studio knowing the canvas exists.
    const withClip = snapshotWith({
      ...snapshot,
      content_links: [
        {
          id: 'ecl_1',
          episode_id: 'dep_1',
          content_type: 'draft',
          content_ref_id: 'drf_1',
          role: 'candidate',
          title: '第一个镜头',
          status: null,
          output_asset_id: 'ast_1',
          thumbnail_url: 'https://example.test/a.png',
        },
      ],
    });
    const added = missingDomainNodes({ nodes: [], edges: [] }, withClip);
    const clip = added.find((n) => n.kind === 'clip');
    expect(clip?.binding).toEqual({ kind: 'clip', episode_id: 'dep_1', draft_id: 'drf_1' });

    // And it is not seeded twice once it is on the canvas.
    const already: CanvasGraph = {
      nodes: [
        {
          id: 'cnd_c',
          kind: 'clip',
          position: { x: 0, y: 0 },
          binding: { kind: 'clip', episode_id: 'dep_1', draft_id: 'drf_1' },
        },
      ],
      edges: [],
    };
    expect(missingDomainNodes(already, withClip).some((n) => n.kind === 'clip')).toBe(false);
  });

  it('renders a seeded clip with the title and thumbnail from hydration', () => {
    const withClip = snapshotWith({
      ...snapshot,
      content_links: [
        {
          id: 'ecl_1',
          episode_id: 'dep_1',
          content_type: 'draft',
          content_ref_id: 'drf_1',
          role: 'candidate',
          title: '第一个镜头',
          status: null,
          output_asset_id: 'ast_1',
          thumbnail_url: 'https://example.test/a.png',
        },
      ],
    });
    const seeded = missingDomainNodes({ nodes: [], edges: [] }, withClip);
    const { nodes } = graphToFlow({ nodes: seeded, edges: [] }, withClip);
    const clip = nodes.find((n) => n.data.kind === 'clip');
    expect(clip?.data.label).toBe('第一个镜头');
    expect(clip?.data.thumbnailUrl).toBe('https://example.test/a.png');
    expect(clip?.data.stale).toBe(false);
  });

  it('adds only the episode created elsewhere, never a duplicate', () => {
    const existing: CanvasGraph = {
      nodes: [
        { id: 'cnd_s', kind: 'series', position: { x: 0, y: 0 }, binding: { kind: 'series' } },
        {
          id: 'cnd_e',
          kind: 'episode',
          position: { x: 0, y: 0 },
          binding: { kind: 'episode', episode_id: 'dep_1' },
        },
      ],
      edges: [],
    };
    expect(missingDomainNodes(existing, snapshot)).toEqual([]);

    const withNewEpisode = snapshotWith({
      ...snapshot,
      episodes: [
        ...snapshot.episodes,
        {
          id: 'dep_2',
          season_number: 1,
          episode_number: 2,
          episode_kind: 'main',
          title: '第二集',
          synopsis: null,
          status: 'draft',
          canonical_work_id: null,
          script: null,
        },
      ],
    });
    const added = missingDomainNodes(existing, withNewEpisode);
    expect(added).toHaveLength(1);
    expect(added[0]!.binding).toEqual({ kind: 'episode', episode_id: 'dep_2' });
  });
});
describe('image node hydration', () => {
  it('renders an uploaded picture from the resolved asset url', () => {
    const graph: CanvasGraph = {
      nodes: [
        {
          id: 'cnd_i',
          kind: 'image',
          position: { x: 0, y: 0 },
          binding: { kind: 'image', asset_id: 'ast_1' },
        },
      ],
      edges: [],
    };
    const snap = snapshotWith({
      assets: {
        ast_1: { url: 'https://example.test/x.png', media_type: 'image', width: 8, height: 8 },
      },
    });
    const { nodes } = graphToFlow(graph, snap);
    expect(nodes[0]!.data.thumbnailUrl).toBe('https://example.test/x.png');
    expect(nodes[0]!.data.stale).toBe(false);
  });

  it('marks a picture stale when its asset no longer resolves', () => {
    // Deleted, or never this caller's to read — the server simply omits it.
    const graph: CanvasGraph = {
      nodes: [
        {
          id: 'cnd_i',
          kind: 'image',
          position: { x: 0, y: 0 },
          binding: { kind: 'image', asset_id: 'ast_gone' },
        },
      ],
      edges: [],
    };
    const { nodes } = graphToFlow(graph, emptySnapshot);
    expect(nodes[0]!.data.stale).toBe(true);
  });

  it('leaves an empty picture placeholder alone', () => {
    const graph: CanvasGraph = {
      nodes: [{ id: 'cnd_i', kind: 'image', position: { x: 0, y: 0 } }],
      edges: [],
    };
    const { nodes } = graphToFlow(graph, emptySnapshot);
    expect(nodes[0]!.data.stale).toBe(false);
  });
});
