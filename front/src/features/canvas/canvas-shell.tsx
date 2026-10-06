'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { useToast } from '@/components/ui/toast';
import { EmptyState, ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { useMinWidth } from '@/lib/use-media-query';

import { getCanvasProject, type CanvasGraph, type CanvasProject } from './api';
import { CanvasView } from './canvas-view';
import { missingDomainNodes } from './graph-convert';
import { restoreCanvasTaskCard, type CanvasAgentTask } from './agent-api';
import { WorkbenchPanel } from './workbench-panel';
import { useCanvasSync } from './use-canvas-sync';

function SaveIndicator({
  status,
  lastError,
}: {
  status: ReturnType<typeof useCanvasSync>['status'];
  lastError: string | null;
}) {
  const t = useTranslations('canvas');
  if (status === 'idle') return null;
  const tone =
    status === 'conflict' || status === 'error'
      ? 'text-danger'
      : status === 'saving'
        ? 'text-muted'
        : 'text-success';
  return (
    <span
      className={`text-xs ${tone}`}
      title={status === 'error' ? (lastError ?? undefined) : undefined}
    >
      {t(`save.${status}`)}
    </span>
  );
}

/** A quiet dot, not a banner.
 *
 * Losing the stream costs live updates from other windows, not the ability to
 * work: every write carries its own catch-up read, so the canvas stays correct
 * either way. Anything louder would imply the session is broken when it is not.
 */
function LiveIndicator({ live }: { live: boolean }) {
  const t = useTranslations('canvas');
  return (
    <span
      className="inline-flex items-center gap-1 text-xs text-muted"
      title={t(live ? 'live.on' : 'live.off')}
    >
      <span
        aria-hidden="true"
        className={`size-1.5 rounded-full ${live ? 'bg-success' : 'bg-border'}`}
      />
      <span className="sr-only">{t(live ? 'live.on' : 'live.off')}</span>
    </span>
  );
}

function CanvasBody({ initial }: { initial: CanvasProject }) {
  const t = useTranslations('canvas');
  const { notify } = useToast();
  const {
    project,
    graph: serverGraph,
    status,
    lastError,
    live,
    agentRevision,
    save,
    flush,
    refreshSnapshot,
  } = useCanvasSync(initial.id, initial);
  const [workbenchOpen, setWorkbenchOpen] = useState(false);

  // Objects created elsewhere (script studio, dashboard) appear as new nodes
  // the first time the canvas sees them, rather than needing to be re-added
  // by hand. Seeded once per load, then persisted like any other layout edit.
  const graph = useMemo<CanvasGraph>(() => {
    const added = missingDomainNodes(serverGraph, project.snapshot);
    if (added.length === 0) return serverGraph;
    return { nodes: [...serverGraph.nodes, ...added], edges: serverGraph.edges };
  }, [serverGraph, project.snapshot]);

  const seeded = graph !== serverGraph;
  useEffect(() => {
    if (seeded) save(graph);
  }, [seeded, graph, save]);

  // No read-only mode: an active co-creator is allowed to arrange a shared
  // series' canvas, exactly as they may already manage its episodes and
  // scripts. The owner-only boundary is about *actions* reachable from a node
  // (timeline editor, publish, trash, deleting the canvas), gated on
  // `viewer_role` where those are added — not about the canvas surface.
  const onCommit = useCallback((next: CanvasGraph) => save(next), [save]);

  const reloadSnapshot = useCallback(() => {
    // Re-read the hydration snapshot after a card starts binding something it
    // does not describe. Two cases: an upload (the durable signed URL is
    // minted server-side, so the canvas re-reads instead of trusting the
    // one-off URL the upload returned — that one expires and would leave a
    // broken image behind) and a skill picked out of the prompt library
    // (hydration decides `stale` from `snapshot.skills`, so without the
    // re-read the card comes back marked broken).
    //
    // `flush` first: the save carrying the new `binding.asset_id` is still in
    // flight at this point, and a GET that overtakes it comes back without
    // the asset — which the client then renders as a stale card, and adopts
    // as the truth, dropping the binding entirely.
    void flush()
      .then(() => refreshSnapshot())
      .catch(() => undefined);
  }, [flush, refreshSnapshot]);

  /** Re-land a result whose card was deleted.
   *
   * The new card reaches this window the same way the original did — the
   * server's change frame off the canvas stream — so there is nothing to
   * merge in by hand here. `flush` first, for the same reason the upload path
   * does it: a write still in flight would otherwise be diffed against a base
   * that does not yet know about the card. */
  const restoreTask = useCallback(
    async (task: CanvasAgentTask) => {
      await flush();
      try {
        await restoreCanvasTaskCard(task.id);
      } catch (cause) {
        notify(cause instanceof Error ? cause.message : String(cause), 'error');
      }
    },
    [flush, notify],
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-medium text-text">{project.title}</h1>
          <p className="text-xs text-muted">
            {t(`mode.${project.mode}`)}
            {project.viewer_role === 'collaborator' ? ` · ${t('collaboratorBadge')}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SaveIndicator status={status} lastError={lastError} />
          <LiveIndicator live={live} />
          <button
            type="button"
            className="rounded-[var(--radius-sm)] px-2 py-1 text-xs text-muted transition-colors hover:bg-surface-soft hover:text-text"
            aria-expanded={workbenchOpen}
            onClick={() => setWorkbenchOpen((open) => !open)}
          >
            {t('workbench.title')}
          </button>
        </div>
      </header>
      {workbenchOpen ? (
        // A disclosure rather than a second permanent sidebar: the canvas is
        // already desktop-gated at 768px and the properties panel owns the
        // right edge, so a fixed second column would squeeze the surface the
        // whole feature is about.
        <section className="max-h-52 overflow-y-auto border-b border-border px-4 py-2">
          <WorkbenchPanel
            canvasId={project.id}
            revision={agentRevision}
            onRestoreTask={restoreTask}
          />
        </section>
      ) : null}
      <div className="min-h-0 flex-1">
        <CanvasView
          canvasId={project.id}
          graph={graph}
          snapshot={project.snapshot}
          onCommit={onCommit}
          onSnapshotStale={reloadSnapshot}
          exportName={project.title}
          onImportFailed={() => notify(t('importFailed'), 'error')}
        />
      </div>
    </div>
  );
}

export function CanvasShell({ canvasId }: { canvasId: string }) {
  const t = useTranslations('canvas');
  // The md gate only — unlike the timeline editor there is no WebCodecs
  // dependency here, so restricting the browser would be a cost with no
  // corresponding capability requirement.
  const wide = useMinWidth('md');
  const { status } = useSession();
  const [project, setProject] = useState<CanvasProject | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Wait for the session to resolve. The access token lives in memory only
    // and is re-derived from the refresh cookie on a cold load, so firing
    // this immediately produces a 401 on every reload — recovered by the
    // client's refresh-and-retry, but a wasted round trip and a real error
    // in the logs.
    if (status !== 'authenticated') return undefined;
    let cancelled = false;
    getCanvasProject(canvasId)
      .then((loaded) => {
        if (cancelled) return;
        setProject(loaded);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [canvasId, status]);

  if (!wide) {
    return <EmptyState title={t('gateDesktopTitle')} description={t('gateDesktopHint')} />;
  }
  if (error) {
    return <ErrorNotice title={t('loadFailed')} detail={error} />;
  }
  if (!project) {
    return <Skeleton className="h-full w-full" />;
  }
  // Keyed so switching canvases remounts the body — `useCanvasSync` seeds
  // itself from `initial` once and never re-reads it.
  return <CanvasBody key={project.id} initial={project} />;
}
