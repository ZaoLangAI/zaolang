import type { BlockingSet, Vec3 } from '../types';
import { DEG } from './math';

/**
 * Set geometry the compiler reasons about: every prop as an oriented box.
 *
 * Two consumers, two questions:
 * - the camera asks "is anything between me and the subject?" (`lineOfSightClear`);
 * - walkers ask "which floor cells can I stand in?" (`WalkGrid`, A* over a
 *   0.2m grid with the props' footprints inflated by a body radius).
 *
 * Everything is deterministic — same document, same paths, same framing —
 * which the exported reference video depends on.
 */

export interface Obstacle {
  id: string;
  cx: number;
  cz: number;
  /** Half extents in the prop's own frame. */
  hx: number;
  hz: number;
  cos: number;
  sin: number;
  y0: number;
  y1: number;
  /** A door opening is walkable (but still blocks the camera when closed). */
  walkable: boolean;
}

const MIN_HALF_THICKNESS = 0.05;

export function setObstacles(set: BlockingSet): Obstacle[] {
  return (set.props ?? []).map((prop) => {
    const [x = 0, y = 0, z = 0] = prop.position;
    const [sx = 1, sy = 1, sz = 1] = prop.scale;
    const depth = prop.primitive === 'plane' ? 0.08 : sz;
    const yaw = prop.rotation_y_deg * DEG;
    return {
      id: prop.id,
      cx: x,
      cz: z,
      hx: Math.max(sx / 2, MIN_HALF_THICKNESS),
      hz: Math.max(depth / 2, MIN_HALF_THICKNESS),
      cos: Math.cos(yaw),
      sin: Math.sin(yaw),
      y0: y,
      y1: y + sy,
      walkable: prop.color_role === 'door' || prop.color_role === 'floor',
    };
  });
}

/** World (x, z) → the obstacle's local frame (inverse of its yaw about +Y). */
function toLocal(o: Obstacle, x: number, z: number): [number, number] {
  const dx = x - o.cx;
  const dz = z - o.cz;
  return [dx * o.cos - dz * o.sin, dx * o.sin + dz * o.cos];
}

export function footprintContains(o: Obstacle, x: number, z: number, inflate = 0): boolean {
  const [lx, lz] = toLocal(o, x, z);
  return Math.abs(lx) <= o.hx + inflate && Math.abs(lz) <= o.hz + inflate;
}

/** Slab test of segment p0→p1 against the obstacle's box, `[tMin, tMax]` in
 * segment parameter space, or `null` when they do not meet. */
function segmentBox(o: Obstacle, p0: Vec3, p1: Vec3): [number, number] | null {
  const [ax, az] = toLocal(o, p0[0], p0[2]);
  const [bx, bz] = toLocal(o, p1[0], p1[2]);
  const origin = [ax, p0[1], az];
  const delta = [bx - ax, p1[1] - p0[1], bz - az];
  const lo = [-o.hx, o.y0, -o.hz];
  const hi = [o.hx, o.y1, o.hz];
  let tMin = 0;
  let tMax = 1;
  for (let axis = 0; axis < 3; axis += 1) {
    const d = delta[axis]!;
    const start = origin[axis]!;
    if (Math.abs(d) < 1e-9) {
      if (start < lo[axis]! || start > hi[axis]!) return null;
      continue;
    }
    let t0 = (lo[axis]! - start) / d;
    let t1 = (hi[axis]! - start) / d;
    if (t0 > t1) [t0, t1] = [t1, t0];
    tMin = Math.max(tMin, t0);
    tMax = Math.min(tMax, t1);
    if (tMin > tMax) return null;
  }
  return [tMin, tMax];
}

/**
 * Nothing solid between `from` and `to`. `ignoreNearTarget` metres at the
 * target end are forgiven, so a subject leaning on a desk or sitting behind
 * a counter is not "occluded" by the very furniture they touch.
 */
export function lineOfSightClear(
  obstacles: Obstacle[],
  from: Vec3,
  to: Vec3,
  ignoreNearTarget = 0.35,
): boolean {
  const length = Math.hypot(to[0] - from[0], to[1] - from[1], to[2] - from[2]);
  if (length < 1e-6) return true;
  const limit = Math.max(0, 1 - ignoreNearTarget / length);
  for (const obstacle of obstacles) {
    const hit = segmentBox(obstacle, from, to);
    if (hit && hit[0] < limit) return false;
  }
  return true;
}

export function pointInsideSolid(obstacles: Obstacle[], point: Vec3, pad = 0.05): boolean {
  return obstacles.some(
    (o) =>
      point[1] >= o.y0 - pad &&
      point[1] <= o.y1 + pad &&
      footprintContains(o, point[0], point[2], pad),
  );
}

// ---------------------------------------------------------------------------
// Walking
// ---------------------------------------------------------------------------

const CELL = 0.2;
/** Half a shoulder width plus a little clearance. */
export const BODY_RADIUS = 0.3;
/** Only things you would walk into block walking: not lamps, not wall art. */
const MAX_OBSTACLE_BOTTOM = 0.6;
const MIN_OBSTACLE_HEIGHT = 0.12;

export interface Circle {
  x: number;
  z: number;
  r: number;
}

export class WalkGrid {
  readonly cols: number;
  readonly rows: number;
  private readonly minX: number;
  private readonly minZ: number;
  private readonly blocked: Uint8Array;

  constructor(set: BlockingSet, obstacles: Obstacle[]) {
    // One metre of apron beyond the set so a walker may leave through an
    // edge without the planner treating the boundary as a wall.
    this.minX = -set.width_m / 2 - 1;
    this.minZ = -set.depth_m / 2 - 1;
    this.cols = Math.ceil((set.width_m + 2) / CELL);
    this.rows = Math.ceil((set.depth_m + 2) / CELL);
    this.blocked = new Uint8Array(this.cols * this.rows);
    const solid = obstacles.filter(
      (o) => !o.walkable && o.y0 <= MAX_OBSTACLE_BOTTOM && o.y1 - o.y0 >= MIN_OBSTACLE_HEIGHT,
    );
    for (let row = 0; row < this.rows; row += 1) {
      for (let col = 0; col < this.cols; col += 1) {
        const [x, z] = this.center(col, row);
        if (solid.some((o) => footprintContains(o, x, z, BODY_RADIUS))) {
          this.blocked[row * this.cols + col] = 1;
        }
      }
    }
  }

  center(col: number, row: number): [number, number] {
    return [this.minX + (col + 0.5) * CELL, this.minZ + (row + 0.5) * CELL];
  }

  cellOf(x: number, z: number): [number, number] {
    const col = Math.min(this.cols - 1, Math.max(0, Math.floor((x - this.minX) / CELL)));
    const row = Math.min(this.rows - 1, Math.max(0, Math.floor((z - this.minZ) / CELL)));
    return [col, row];
  }

  private free(col: number, row: number, extra: Circle[]): boolean {
    if (col < 0 || row < 0 || col >= this.cols || row >= this.rows) return false;
    if (this.blocked[row * this.cols + col]) return false;
    if (extra.length === 0) return true;
    const [x, z] = this.center(col, row);
    return !extra.some((c) => Math.hypot(x - c.x, z - c.z) < c.r);
  }

  isFree(x: number, z: number, extra: Circle[] = []): boolean {
    const [col, row] = this.cellOf(x, z);
    return this.free(col, row, extra);
  }

  /** Nearest walkable point to (x, z) — breadth-first over rings of cells,
   * ties broken by true distance, so the same input always lands the same. */
  nearestFree(x: number, z: number, extra: Circle[] = []): [number, number] {
    const [col, row] = this.cellOf(x, z);
    if (this.free(col, row, extra) && this.isFree(x, z, extra)) return [x, z];
    for (let radius = 1; radius < Math.max(this.cols, this.rows); radius += 1) {
      let best: [number, number] | null = null;
      let bestDistance = Infinity;
      for (let dr = -radius; dr <= radius; dr += 1) {
        for (let dc = -radius; dc <= radius; dc += 1) {
          if (Math.max(Math.abs(dr), Math.abs(dc)) !== radius) continue;
          if (!this.free(col + dc, row + dr, extra)) continue;
          const [cx, cz] = this.center(col + dc, row + dr);
          const distance = Math.hypot(cx - x, cz - z);
          if (distance < bestDistance) {
            bestDistance = distance;
            best = [cx, cz];
          }
        }
      }
      if (best) return best;
    }
    return [x, z];
  }

  private clearLine(a: [number, number], b: [number, number], extra: Circle[]): boolean {
    const steps = Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / (CELL / 2));
    for (let i = 0; i <= steps; i += 1) {
      const u = steps === 0 ? 0 : i / steps;
      if (!this.isFree(a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, extra)) return false;
    }
    return true;
  }

  /**
   * A* (8-connected, no corner cutting) from `from` to `to`, then
   * string-pulled to the fewest straight legs. Returns ground points
   * including both ends; a straight line when nothing is in the way.
   */
  plan(from: Vec3, to: Vec3, extra: Circle[] = []): Vec3[] {
    const start: [number, number] = [from[0], from[2]];
    const goal = this.nearestFree(to[0], to[2], extra);
    if (this.clearLine(start, goal, extra)) return [from, [goal[0], 0, goal[1]]];

    const [sc, sr] = this.cellOf(start[0], start[1]);
    const [gc, gr] = this.cellOf(goal[0], goal[1]);
    const index = (c: number, r: number) => r * this.cols + c;
    const total = this.cols * this.rows;
    const g = new Float64Array(total).fill(Infinity);
    const parent = new Int32Array(total).fill(-1);
    const closed = new Uint8Array(total);
    const open: number[] = [];
    const h = (c: number, r: number) => {
      const dx = Math.abs(c - gc);
      const dz = Math.abs(r - gr);
      return Math.max(dx, dz) + (Math.SQRT2 - 1) * Math.min(dx, dz);
    };
    g[index(sc, sr)] = 0;
    open.push(index(sc, sr));
    const f = (i: number) => g[i]! + h(i % this.cols, Math.floor(i / this.cols));
    let found = false;
    while (open.length > 0) {
      // Small grids: a linear scan beats maintaining a heap, and keeps the
      // tie-break (lowest index) explicit and deterministic.
      let bestAt = 0;
      for (let k = 1; k < open.length; k += 1) {
        const a = open[k]!;
        const b = open[bestAt]!;
        if (f(a) < f(b) - 1e-9 || (Math.abs(f(a) - f(b)) <= 1e-9 && a < b)) bestAt = k;
      }
      const current = open.splice(bestAt, 1)[0]!;
      if (closed[current]) continue;
      closed[current] = 1;
      const cc = current % this.cols;
      const cr = Math.floor(current / this.cols);
      if (cc === gc && cr === gr) {
        found = true;
        break;
      }
      for (let dr = -1; dr <= 1; dr += 1) {
        for (let dc = -1; dc <= 1; dc += 1) {
          if (dr === 0 && dc === 0) continue;
          const nc = cc + dc;
          const nr = cr + dr;
          // The start cell may sit inside an inflated footprint (a mark
          // touching a table); let the walker step out of it.
          const startCell = nc === sc && nr === sr;
          if (!startCell && !this.free(nc, nr, extra)) continue;
          if (
            dr !== 0 &&
            dc !== 0 &&
            (!this.free(cc + dc, cr, extra) || !this.free(cc, cr + dr, extra))
          ) {
            continue;
          }
          const next = index(nc, nr);
          if (closed[next]) continue;
          const cost = g[current]! + (dr !== 0 && dc !== 0 ? Math.SQRT2 : 1);
          if (cost < g[next]!) {
            g[next] = cost;
            parent[next] = current;
            open.push(next);
          }
        }
      }
    }
    if (!found) return [from, [goal[0], 0, goal[1]]];

    const cells: [number, number][] = [];
    for (let at = index(gc, gr); at !== -1; at = parent[at]!) {
      cells.push(this.center(at % this.cols, Math.floor(at / this.cols)));
    }
    cells.reverse();
    cells[0] = start;
    cells[cells.length - 1] = goal;
    const pulled: [number, number][] = [start];
    let anchor = 0;
    while (anchor < cells.length - 1) {
      let next = cells.length - 1;
      while (next > anchor + 1 && !this.clearLine(cells[anchor]!, cells[next]!, extra)) next -= 1;
      pulled.push(cells[next]!);
      anchor = next;
    }
    return pulled.map(([x, z]) => [x, 0, z]);
  }
}
