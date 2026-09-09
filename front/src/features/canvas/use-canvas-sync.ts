'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  applyCanvasGraphOps,
  getCanvasProject,
  type CanvasChange,
  type CanvasGraph,
  type CanvasProject,
} from './api';
import { applyChanges, diffGraph, graphFromProject } from './graph-ops';
import { useCanvasEvents } from './use-canvas-events';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'conflict' | 'error';

/**
 * Autosave for the canvas.
 *
 * Same shape as the timeline editor's sync loop (`drama-editor.tsx`): edits
 * apply locally first and are pushed onto a single-flight FIFO queue, so a
 * fast sequence of drags never flashes back to an older server state. The
 * differences are deliberate:
 *
 * * The unit of work on the wire is a batch of per-entity operations, not the
 *   whole document. A document-shaped write would collide with the server's
 *   own writes — an Agent run lands a generated card minutes after it started,
 *   whenever that happens to be — and there is no compare-and-set granular
 *   enough to let both through when the granule is the entire graph.
 * * Concurrency is a `revision` per card. A card that moved under you costs
 *   you that card; the other edits in the same flush still land.
 * * A conflict is therefore not a wholesale reload. The server's row for the
 *   conflicted card arrives in the same response's change feed and is adopted
 *   on the spot. Only a *gap* — a cursor the feed can no longer reconstruct —
 *   falls back to re-reading the canvas.
 */
/**
 * `initial` seeds the hook and is never re-read: the owning component is
 * mounted with a `key` of the canvas id, so switching canvases remounts
 * rather than mutating this state in place. Syncing it back through an effect
 * would be a cascading render for a case that cannot happen.
 */
export function useCanvasSync(canvasId: string, initial: CanvasProject) {
  const [project, setProject] = useState<CanvasProject>(initial);
  const [graph, setGraph] = useState<CanvasGraph>(() => graphFromProject(initial));
  const [status, setStatus] = useState<SaveStatus>('idle');
  const [lastError, setLastError] = useState<string | null>(null);
  /** Whether the change stream is currently attached. Drives the header dot;
   * the canvas stays fully usable while it is false, because every write also
   * carries its own catch-up read. */
  const [live, setLive] = useState(false);
  /** Bumped whenever the stream carries an agent frame. The workbench
   * re-reads on it rather than rebuilding a run from deltas — the
   * server's view of a run is the only one worth showing. */
  const [agentRevision, setAgentRevision] = useState(0);

  /** The last arrangement the server acknowledged. Every diff is taken against
   * this, never against the previous local state — that is what lets "add a
   * card then drag it four times" collapse into one create at the final spot. */
  const baseRef = useRef<CanvasGraph>(graphFromProject(initial));
  const seqRef = useRef(initial.change_seq);
  const queueRef = useRef<CanvasGraph[]>([]);
  const inflightRef = useRef(false);
  const pumpRef = useRef<() => void>(() => {});
  /** Frames that arrived while a write was in flight.
   *
   * They cannot be applied on the spot — folding a server state that predates
   * the pending edit would roll it back under the user's cursor — but they
   * must not be dropped either: `use-canvas-events` has already advanced its
   * stream cursor past them, so a reconnect will not replay them. Held here
   * and merged in once the flush settles. */
  const deferredRef = useRef<CanvasChange[]>([]);
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flashSaved = useCallback(() => {
    setStatus('saved');
    setLastError(null);
    if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
    savedTimerRef.current = setTimeout(() => setStatus('idle'), 2000);
  }, []);

  const adopt = useCallback((next: CanvasGraph, seq: number) => {
    baseRef.current = next;
    seqRef.current = seq;
    setGraph(next);
  }, []);

  const reload = useCallback(async () => {
    const fresh = await getCanvasProject(canvasId);
    setProject(fresh);
    adopt(graphFromProject(fresh), fresh.change_seq);
    return fresh;
  }, [adopt, canvasId]);

  /**
   * Re-reads hydration only, leaving the graph and the cursor alone.
   *
   * Used after an upload, which needs the asset's durable signed URL. Taking
   * the whole response would also take its cards — and anything the user added
   * while that request was in flight would be wiped by a graph that predates
   * it. The snapshot cannot conflict this way: it is server-derived and
   * nothing local writes it.
   */
  const refreshSnapshot = useCallback(async () => {
    const fresh = await getCanvasProject(canvasId);
    setProject((current) => ({ ...current, snapshot: fresh.snapshot }));
  }, [canvasId]);

  /** Apply frames buffered during a flush. Safe to call whenever idle. */
  const drain = useCallback(() => {
    const deferred = deferredRef.current;
    if (deferred.length === 0 || inflightRef.current || queueRef.current.length > 0) return;
    deferredRef.current = [];
    const settled = applyChanges(baseRef.current, deferred);
    baseRef.current = settled;
    const highest = deferred.reduce((max, change) => Math.max(max, change.seq), 0);
    if (highest > seqRef.current) seqRef.current = highest;
    setGraph(settled);
  }, []);

  const pump = useCallback(() => {
    if (inflightRef.current) return;
    // Only the newest queued arrangement matters: each entry is a complete
    // desired state, so the intermediate ones describe layouts nobody will
    // ever see again. The diff against `baseRef` reduces them to one batch.
    const desired = queueRef.current.at(-1);
    if (!desired) return;
    queueRef.current = [];

    const ops = diffGraph(baseRef.current, desired);
    if (ops.length === 0) {
      // Nothing actually moved — a commit that only reordered React state, or
      // a drag that rounded back to where it started.
      setGraph(desired);
      baseRef.current = desired;
      return;
    }

    inflightRef.current = true;
    setStatus('saving');

    void applyCanvasGraphOps(canvasId, { baseSeq: seqRef.current, ops })
      .then((result) => {
        // The server states this rather than leaving it to be inferred. An
        // empty `changes` is also what a batch of pure conflicts looks like,
        // and sequence numbers are monotonic but not dense, so no comparison
        // of the numbers could tell the two apart. The write itself landed;
        // only the catch-up is missing, so re-read to converge.
        if (result.gap) {
          void reload().catch(() => undefined);
          return;
        }

        // Fold the server's view over the arrangement we just sent: our own
        // writes come back with real revisions, another session's edits arrive
        // the same way, and conflicted cards revert to the server's row.
        //
        // Anything deferred while this was in flight goes in too, merged by
        // sequence — a buffered frame can be older than one in the response,
        // and applying it afterwards would regress that card.
        const deferred = deferredRef.current;
        deferredRef.current = [];
        const incoming =
          deferred.length === 0
            ? result.changes
            : [...result.changes, ...deferred].sort((a, b) => a.seq - b.seq);
        const settled = applyChanges(desired, incoming);
        baseRef.current = settled;
        seqRef.current = result.change_seq;

        // Only adopt into rendered state once nothing else is pending;
        // otherwise an in-flight edit would be rolled back under the user.
        if (queueRef.current.length === 0) setGraph(settled);

        if (result.conflicts.length > 0) {
          // Visible, but not an error: the rest of the batch landed and the
          // conflicted cards now show what the server actually has.
          setStatus('conflict');
          setLastError(null);
          return;
        }
        flashSaved();
      })
      .catch((error: unknown) => {
        queueRef.current = [];
        // Any failure (network drop, 5xx, a batch the server rejects) must
        // stay visible: the user's last arrangement is NOT saved, and
        // returning to 'idle' would tell them the opposite. Rethrowing would
        // only produce an unhandled rejection on this voided chain.
        setStatus('error');
        setLastError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        inflightRef.current = false;
        if (queueRef.current.length > 0) {
          pumpRef.current();
          return;
        }
        // Frames that landed during the `.then` itself, or during a failed
        // flush. Nothing else will come back for them.
        drain();
      });
  }, [canvasId, drain, flashSaved, reload]);

  useEffect(() => {
    pumpRef.current = pump;
  }, [pump]);

  const save = useCallback((next: CanvasGraph) => {
    queueRef.current.push(next);
    pumpRef.current();
  }, []);

  /**
   * Fold changes another session made into the local graph.
   *
   * Skipped entirely while this window has writes queued or in flight: the
   * incoming frames describe a server state that predates them, and adopting
   * it would roll the user's own pending edits back under their cursor. The
   * next flush reconciles anyway — its response carries every change after
   * `seqRef`, which includes whatever is being dropped here.
   */
  const receive = useCallback((incoming: CanvasChange[], seq: number) => {
    if (incoming.some((change) => change.entity_type.startsWith('agent'))) {
      setAgentRevision((current) => current + 1);
    }
    if (inflightRef.current || queueRef.current.length > 0) {
      // Buffered rather than discarded — see `deferredRef`.
      deferredRef.current.push(...incoming);
      return;
    }
    const settled = applyChanges(baseRef.current, incoming);
    baseRef.current = settled;
    if (seq > seqRef.current) seqRef.current = seq;
    setGraph(settled);
  }, []);

  useCanvasEvents(canvasId, true, {
    onChanges: receive,
    // A cursor the feed cannot reconstruct. Re-read rather than apply a
    // partial history as if it were complete.
    onGap: () => void reload().catch(() => undefined),
    onConnectedChange: setLive,
  });

  /**
   * Resolves once nothing is queued or in flight.
   *
   * Anything that re-reads the canvas has to wait for this first: a GET issued
   * alongside a pending write can be answered from the pre-write state, and
   * adopting that response rolls the client back to it. Same reason
   * `drama-editor.tsx` flushes before restore/export.
   */
  const flush = useCallback(
    () =>
      new Promise<void>((resolve) => {
        const settled = () => queueRef.current.length === 0 && !inflightRef.current;
        if (settled()) {
          resolve();
          return;
        }
        const timer = setInterval(() => {
          if (!settled()) return;
          clearInterval(timer);
          resolve();
        }, 30);
      }),
    [],
  );

  useEffect(
    () => () => {
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
    },
    [],
  );

  return {
    project,
    graph,
    status,
    lastError,
    live,
    agentRevision,
    save,
    reload,
    flush,
    refreshSnapshot,
  };
}
