'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { EmptyState } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';
import { randomUuid } from '@/lib/random-id';
import type { ShortformProfile } from '@/lib/api/types';

import * as editorApi from './api';
import { emptyDocument } from './engine/canonical';
import type { CanonicalDocument, EditCommand, ResolvedAsset, TimelineElement } from './engine/ports';
import { EditorGate } from './gate';
import { useEditorUi } from './store';
import { StudioShell } from './studio/studio-shell';
import { useEditorLease } from './use-editor-lease';

/** Caps how many local undo/redo checkpoints are kept per session — unbounded growth is pointless since nobody undoes hundreds of steps back. */
const MAX_UNDO_CHECKPOINTS = 50;

export function DramaEditor({ cutId, draftId }: { cutId: string; draftId: string | null }) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const { lease, token, heldByOther, reclaim, reclaiming } = useEditorLease(cutId);
  const readonly = useEditorUi((state) => state.readonly);
  const selectedIds = useEditorUi((state) => state.selectedIds);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const select = useEditorUi((state) => state.select);
  const [cut, setCut] = useState<editorApi.EpisodeCut | null>(null);
  const [document, setDocument] = useState<CanonicalDocument>(emptyDocument());
  const [profiles, setProfiles] = useState<ShortformProfile[]>([]);
  const [defaultProfile, setDefaultProfile] = useState<string | null>(null);
  const [caption, setCaption] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Bumped every time `document`/`cut` is set from a server response (initial
  // load, a successful command, a restore, or a post-conflict resync) — the
  // properties panel's per-clip controls (volume/effects/keyframes/
  // transitions) key off this to force a remount that re-seeds their local
  // optimistic draft state from the fresh props. Without it, a control whose
  // `onCommit` silently failed (e.g. a revision conflict) keeps showing the
  // edit it *tried* to make forever, even after the rest of the app has
  // already recovered — see `recoverFromConflict`.
  const [syncNonce, setSyncNonce] = useState(0);
  // Drives the header's lightweight save-status badge — `apply()`/`restore()`
  // used to only ever call `notify(..., 'error')` on failure, leaving success
  // completely silent (walkthrough finding: "编辑成功没有正面反馈"). A toast
  // per keystroke/slider-drag would be noisy, so this is a quiet inline
  // "已保存" that appears for a couple of seconds instead.
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const savedBadgeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /**
   * Local undo/redo, session-only. `restoreRevision` always creates a *new*
   * immutable revision copying the target's content rather than literally
   * rewinding `head_revision_id` — so this stack stores the *logical*
   * checkpoint ids the user has visited, not a literal pointer into server
   * history. `stack[index]` is always "where we logically are"; undo/redo
   * only ever move `index`, never touch the stack — only a genuinely new
   * edit (or a manual History-panel restore) truncates any redo tail and
   * appends a fresh checkpoint. See `pushCheckpoint`/`undo`/`redo` below.
   */
  const [checkpoints, setCheckpoints] = useState<{ stack: string[]; index: number }>({
    stack: [],
    index: -1,
  });
  const pushCheckpoint = (revisionId: string) => {
    setCheckpoints((current) => {
      const truncated = current.stack.slice(0, current.index + 1);
      truncated.push(revisionId);
      const trimmed =
        truncated.length > MAX_UNDO_CHECKPOINTS
          ? truncated.slice(truncated.length - MAX_UNDO_CHECKPOINTS)
          : truncated;
      return { stack: trimmed, index: trimmed.length - 1 };
    });
  };
  const flashSaved = () => {
    if (savedBadgeTimer.current) clearTimeout(savedBadgeTimer.current);
    setSaveStatus('saved');
    savedBadgeTimer.current = setTimeout(() => setSaveStatus('idle'), 2500);
  };
  useEffect(
    () => () => {
      if (savedBadgeTimer.current) clearTimeout(savedBadgeTimer.current);
    },
    [],
  );

  const reload = useCallback(async () => {
    const next = await editorApi.getCut(cutId);
    setCut(next);
    if (next.head?.document) setDocument(next.head.document);
    setSyncNonce((n) => n + 1);
    // A fresh load (initial mount) or a post-conflict resync both mean "the
    // server state we knew about is gone, start over" — any older local
    // checkpoints could point at a branch that's no longer the one to
    // undo/redo through, so the safest reset is a brand-new single-entry
    // stack anchored at whatever the server now says is head.
    setCheckpoints(next.head_revision_id ? { stack: [next.head_revision_id], index: 0 } : { stack: [], index: -1 });
  }, [cutId]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        await reload();
      } catch (error) {
        if (!cancelled) setLoadError(isApiError(error) ? error.message : t('unavailable'));
      }
      const catalog = await editorApi.loadShortformProfiles();
      if (!cancelled) {
        setProfiles(catalog.profiles);
        setDefaultProfile(catalog.default_profile);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [reload, t]);

  /**
   * A 409 REVISION_CONFLICT means `cut.head_revision_id` no longer matches
   * the server's head (another tab, a reclaimed lease, a retried request
   * that landed twice, ...). Without resyncing, every later `apply`/
   * `restore` call keeps sending that same stale id and keeps failing the
   * same way forever — a permanent, silent-looking freeze where nothing the
   * user does is ever saved. Re-fetching the cut here realigns local state
   * with the server so the *next* command has a valid expectedRevisionId;
   * the just-attempted edit itself was not applied and the user is told to
   * redo it against the refreshed document.
   */
  const recoverFromConflict = async (error: unknown): Promise<boolean> => {
    if (!(isApiError(error) && error.code === 'REVISION_CONFLICT')) return false;
    try {
      await reload();
    } catch {
      // Best-effort resync — the conflict toast below still fires either way.
    }
    notify(t('revisionConflictRefreshed'), 'error');
    return true;
  };

  const apply = async (commands: EditCommand[]) => {
    if (!cut || !lease || !token) return;
    setBusy(true);
    setSaveStatus('saving');
    try {
      const revision = await editorApi.applyCommands(cut.id, {
        batchId: randomUuid(),
        expectedRevisionId: cut.head_revision_id,
        leaseId: lease.id,
        leaseToken: token,
        commands,
      });
      setDocument(revision.document);
      setCut({ ...cut, head_revision_id: revision.id, head: revision });
      setSyncNonce((n) => n + 1);
      pushCheckpoint(revision.id);
      flashSaved();
    } catch (error) {
      setSaveStatus('idle');
      if (!(await recoverFromConflict(error))) {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      }
    } finally {
      setBusy(false);
    }
  };

  /** Shared restore mechanics — see `restore` (manual, from the History panel) vs `undo`/`redo` (checkpoint navigation) for how each uses the result. */
  const performRestore = async (revisionId: string): Promise<editorApi.CutRevision | null> => {
    if (!cut || !lease || !token) return null;
    setBusy(true);
    setSaveStatus('saving');
    try {
      const revision = await editorApi.restoreRevision(cut.id, {
        revisionId,
        expectedRevisionId: cut.head_revision_id,
        leaseId: lease.id,
        leaseToken: token,
      });
      setDocument(revision.document);
      setCut({ ...cut, head_revision_id: revision.id, head: revision });
      setSyncNonce((n) => n + 1);
      flashSaved();
      return revision;
    } catch (error) {
      setSaveStatus('idle');
      if (!(await recoverFromConflict(error))) {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      }
      return null;
    } finally {
      setBusy(false);
    }
  };

  const restore = async (revisionId: string) => {
    const revision = await performRestore(revisionId);
    if (revision) {
      pushCheckpoint(revision.id);
      notify(t('historyRestoreSuccess'), 'success');
    }
  };

  const canUndo = checkpoints.index > 0;
  const canRedo = checkpoints.index < checkpoints.stack.length - 1;

  const undo = async () => {
    if (!canUndo) return;
    const target = checkpoints.stack[checkpoints.index - 1];
    if (!target) return;
    const revision = await performRestore(target);
    if (revision) setCheckpoints((current) => ({ ...current, index: current.index - 1 }));
  };

  const redo = async () => {
    if (!canRedo) return;
    const target = checkpoints.stack[checkpoints.index + 1];
    if (!target) return;
    const revision = await performRestore(target);
    if (revision) setCheckpoints((current) => ({ ...current, index: current.index + 1 }));
  };

  const selected = selectedElement(document, selectedIds[0]);
  const disabled = readonly || busy || !token;
  const assetUrls = cut?.head?.asset_urls ?? {};
  // Keyed off the revision id rather than assetUrls itself: asset_urls only
  // ever changes together with the head revision, and the revision id is a
  // stable primitive the memo can depend on directly.
  const assets: ResolvedAsset[] = useMemo(
    () =>
      Object.entries(assetUrls).map(([assetId, url]) => ({
        asset_id: assetId,
        url,
        mime_type: 'video/mp4',
        duration_ticks: null,
        width: null,
        height: null,
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cut?.head?.id],
  );

  if (loadError) {
    return <EmptyState title={t('unavailable')} description={loadError} />;
  }
  if (!cut) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('loading')} />
      </div>
    );
  }

  return (
    <EditorGate>
      <StudioShell
        cutName={cut.name}
        episodeId={cut.episode_id}
        saveStatus={saveStatus}
        readonly={readonly}
        heldByOther={heldByOther}
        reclaiming={reclaiming}
        onReclaim={() => void reclaim()}
        leaseExpiresAt={lease?.expires_at ?? null}
        document={document}
        assets={assets}
        durationTicks={cut.head?.duration_ticks ?? 0}
        disabled={disabled}
        selected={selected}
        selectedIds={selectedIds}
        caption={caption}
        onCaptionChange={setCaption}
        onSelect={(element) => select([element.id])}
        onApply={(commands) => void apply(commands)}
        onDeleteSelected={() => void apply([{ type: 'delete_elements', element_ids: selectedIds }])}
        onSplitAtPlayhead={() => {
          if (!selected) return;
          void apply([{ type: 'split_element', element_id: selected.id, at_ticks: playheadTicks }]);
        }}
        canUndo={canUndo}
        canRedo={canRedo}
        onUndo={() => void undo()}
        onRedo={() => void redo()}
        revisionId={cut.head_revision_id}
        syncNonce={syncNonce}
        draftId={draftId}
        profiles={profiles}
        defaultProfile={defaultProfile}
        cutId={cut.id}
        leaseId={lease?.id ?? null}
        leaseToken={token}
        onPlanApplied={() => void reload()}
        onRestore={(revisionId) => void restore(revisionId)}
      />
    </EditorGate>
  );
}

function selectedElement(
  document: CanonicalDocument,
  id: string | undefined,
): TimelineElement | undefined {
  if (!id) return undefined;
  for (const track of document.tracks) {
    const found = track.elements.find((element) => element.id === id);
    if (found) return found;
  }
  return undefined;
}
