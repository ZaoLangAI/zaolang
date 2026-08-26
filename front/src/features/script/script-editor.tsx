'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { EmptyState, ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { Link, usePathname, useRouter } from '@/i18n/navigation';
import { isApiError } from '@/lib/api/errors';

import * as scriptApi from './api';
import type { ScriptDetail, ScriptDocument } from './api';
import { clearCreateStream, useCreateStream } from './create-stream-store';
import { ScriptChatPanel } from './script-chat-panel';
import { ScriptDocumentView } from './script-document-view';
import { useScriptTurnStream } from './use-script-turn-stream';

/** Right-side placeholder while a script's content is streaming in (either
 * the first draft or a revision turn) and there is nothing final to show
 * yet — replaces `ScriptDocumentView` rather than rendering it against a
 * stale or empty document. */
function ScriptDocumentLoading({ label, hint }: { label: string; hint: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-14 text-center">
      <Spinner />
      <p className="text-sm font-medium">{label}</p>
      <p className="max-w-xs text-xs text-muted">{hint}</p>
      <div className="mt-2 flex w-full max-w-sm flex-col gap-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    </div>
  );
}

/**
 * The script-writing workspace for one episode: left is the conversation
 * (history + composer), right is the full structured script for whichever
 * turn is currently selected.
 *
 * A script no longer necessarily has a turn by the time this mounts: since
 * `ScriptLanding` now navigates here the instant a new episode is named
 * (the SSE `start` frame, before the first draft has finished streaming —
 * see `create-stream-store.ts`), this may render mid-first-draft, or even
 * land on an episode whose first draft never finished (a stale bookmark,
 * or a page refresh that lost the in-memory stream). `useCreateStream`
 * picks the shared stream back up when it belongs to this `episodeId`.
 */
export function ScriptEditor({
  episodeId,
  pendingLink,
}: {
  episodeId: string;
  /**
   * Carried back from the image studio's "返回文案创作" (`InlineImageResult`)
   * via `/create/script/{episodeId}?linkKind=...&linkLabel=...&linkRefId=...`
   * (see `ScriptEditorPage`). Applied once, the moment `detail` first loads,
   * then stripped from the URL so a refresh never re-applies it.
   */
  pendingLink?: { kind: 'character' | 'scene'; label: string; refId: string };
}) {
  const t = useTranslations('scriptStudio');
  const { notify } = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const [detail, setDetail] = useState<ScriptDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [viewedScript, setViewedScript] = useState<ScriptDocument | null>(null);
  const [firstDraftError, setFirstDraftError] = useState<string | null>(null);
  // A ref, not `useState`: this is purely a run-once guard, never read by
  // render — same pattern as `WorkflowPublishDialog`'s `wasOpen`.
  const pendingLinkApplied = useRef(false);
  const stream = useScriptTurnStream();
  const createStream = useCreateStream(episodeId);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const next = await scriptApi.getScript(episodeId);
        if (cancelled) return;
        setDetail(next);
        setSelectedTurnId(next.turns.at(-1)?.id ?? null);
        setViewedScript(next.script);
      } catch (error) {
        if (!cancelled) setLoadError(isApiError(error) ? error.message : t('unavailable'));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [episodeId, t]);

  // The first draft may still be streaming in from `ScriptLanding`. Once it
  // lands, refetch the canonical script through the normal REST endpoint
  // instead of hand-assembling the turn/document shape here, then release
  // the shared stream so a later "new script" doesn't inherit it.
  const firstDraftResult = createStream?.result ?? null;
  useEffect(() => {
    if (!firstDraftResult) return;
    let cancelled = false;
    void scriptApi
      .getScript(episodeId)
      .then((next) => {
        if (cancelled) return;
        setDetail(next);
        setSelectedTurnId(next.turns.at(-1)?.id ?? null);
        setViewedScript(next.script);
      })
      .catch((error: unknown) => {
        if (!cancelled) notify(isApiError(error) ? error.message : t('unavailable'), 'error');
      })
      .finally(() => {
        if (!cancelled) clearCreateStream(episodeId);
      });
    return () => {
      cancelled = true;
    };
  }, [firstDraftResult, episodeId, notify, t]);

  // Copied into local state (rather than read from the store on every
  // render) so the failure stays on screen even after the store itself
  // moves on — see `create-stream-store.ts`'s `startCreate` for why a fresh
  // attempt elsewhere would otherwise silently clear it out from under us.
  // Adjusted during render rather than in an effect (an effect would commit
  // one stale render first) — same pattern as
  // `NotificationCenterProvider`'s `wasAuthenticated` check.
  const firstDraftStreamError = createStream?.error ?? null;
  if (firstDraftStreamError && firstDraftStreamError !== firstDraftError) {
    setFirstDraftError(firstDraftStreamError);
  }

  const selectTurn = async (turnId: string) => {
    setSelectedTurnId(turnId);
    if (detail && detail.turns.at(-1)?.id === turnId) {
      setViewedScript(detail.script);
      return;
    }
    try {
      const snapshot = await scriptApi.getTurnSnapshot(episodeId, turnId);
      setViewedScript(snapshot.script);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('unavailable'), 'error');
    }
  };

  const isViewingLatest = detail !== null && selectedTurnId === detail.turns.at(-1)?.id;

  const updateLink = async (
    update:
      | { kind: 'character'; name: string; refId: string | null }
      | { kind: 'scene'; heading: string; refId: string | null },
  ) => {
    try {
      const script = await scriptApi.updateScriptLinks(episodeId, {
        characters:
          update.kind === 'character'
            ? [{ name: update.name, character_ref_id: update.refId }]
            : [],
        scenes: update.kind === 'scene' ? [{ heading: update.heading, ref_id: update.refId }] : [],
      });
      setDetail((current) => (current ? { ...current, script } : current));
      setViewedScript(script);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('unavailable'), 'error');
    }
  };

  // Hand-edits (double-click a block/logline/trait, then blur or Ctrl+S —
  // see `EditableInlineText`) never go through the LLM turn machinery: they
  // persist straight to `episode.script_json` via `updateScriptContent`,
  // same non-turn write path as `updateLink` above. Updating `viewedScript`/
  // `detail.script` optimistically (before the network round-trip resolves)
  // is what makes an edit "stick" for the *next* prompt-based revision too —
  // `sendTurn` below always reads `viewedScript ?? detail.script` as the
  // basis it sends as `current_script`, so an edit made seconds ago is
  // already part of what the next turn revises, with no separate merge step
  // needed. A failed save rolls the optimistic update back and surfaces a
  // toast, so client state never drifts from what's actually persisted.
  const saveContent = async (nextScript: ScriptDocument) => {
    const previous = viewedScript ?? detail?.script ?? null;
    setViewedScript(nextScript);
    setDetail((current) => (current ? { ...current, script: nextScript } : current));
    try {
      const saved = await scriptApi.updateScriptContent(episodeId, nextScript);
      setViewedScript(saved);
      setDetail((current) => (current ? { ...current, script: saved } : current));
    } catch (error) {
      setViewedScript(previous);
      setDetail((current) => (current && previous ? { ...current, script: previous } : current));
      notify(isApiError(error) ? error.message : t('unavailable'), 'error');
    }
  };

  // Runs once, the moment `detail` first has a script to match against.
  // Exact-matches `pendingLink.label` against a character name/scene
  // heading (never fuzzy — a near-miss silently linking the wrong card
  // would be worse than not linking at all) and overwrites any existing
  // link on that entry without confirmation, same as `ScriptLinkPicker`'s
  // own click-to-link. Either way, the URL is cleaned up immediately after
  // so a refresh never re-applies (or re-fails) it.
  useEffect(() => {
    if (pendingLink && !pendingLinkApplied.current && detail) {
      pendingLinkApplied.current = true;
      const script = detail.script;
      const matched =
        pendingLink.kind === 'character'
          ? script.characters.some((character) => character.name === pendingLink.label)
          : script.scenes.some((scene) => scene.heading === pendingLink.label);
      if (matched) {
        // `updateLink` itself only calls `setDetail`/`setViewedScript` after
        // its own `await`, in response to the PATCH's result — an ordinary
        // network-triggered update, not a synchronous render-loop setState.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void updateLink(
          pendingLink.kind === 'character'
            ? { kind: 'character', name: pendingLink.label, refId: pendingLink.refId }
            : { kind: 'scene', heading: pendingLink.label, refId: pendingLink.refId },
        );
      } else {
        notify(t('linkReturnNotFound'), 'error');
      }
      router.replace(pathname);
    }
    // `updateLink`/`notify`/`router`/`pathname` are stable enough across
    // renders on this page that omitting them avoids re-running this on
    // every unrelated re-render; `pendingLinkApplied` is what actually
    // guards re-entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingLink, detail]);

  const sendTurn = (message: string, referencedSkillIds: string[]) => {
    if (!detail) return;
    // Always the document actually on screen, not necessarily the episode's
    // true latest turn — the user may have browsed back to an earlier
    // version via `selectTurn` and expects to keep editing from there.
    const currentScript = viewedScript ?? detail.script;
    void stream.run(
      { kind: 'turn', episodeId, message, referencedSkillIds, currentScript },
      (result) => {
        setDetail((current) =>
          current
            ? {
                ...current,
                script: result.script,
                turns: [
                  ...current.turns,
                  {
                    id: result.turn_id,
                    turn_no: result.turn_no,
                    user_message: message,
                    summary: result.summary,
                    referenced_skill_ids: referencedSkillIds,
                    created_at: new Date().toISOString(),
                  },
                ],
              }
            : current,
        );
        setSelectedTurnId(result.turn_id);
        setViewedScript(result.script);
        if (result.degraded) notify(t('turnDegraded'), 'error');
      },
    );
  };

  if (loadError) return <ErrorNotice title={loadError} />;
  if (!detail) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('loading')} />
      </div>
    );
  }

  const backToScripts = (
    <Link
      href="/create/script"
      className="inline-flex h-11 items-center justify-center rounded-[var(--radius-sm)] border border-border bg-surface-soft px-4 text-sm font-medium text-text transition-colors hover:border-border-strong hover:bg-surface-raised"
    >
      {t('backToScripts')}
    </Link>
  );

  const hasTurns = detail.turns.length > 0;
  const firstDraftStreaming = !hasTurns && (createStream?.streaming ?? false);

  if (!hasTurns && !firstDraftStreaming) {
    if (firstDraftError) {
      return (
        <ErrorNotice title={firstDraftError} detail={t('firstDraftFailedHint')} action={backToScripts} />
      );
    }
    return (
      <EmptyState
        title={t('firstDraftMissing')}
        description={t('firstDraftMissingHint')}
        action={backToScripts}
      />
    );
  }

  const documentStreaming = firstDraftStreaming || stream.streaming;

  // Both columns share this exact height at the desktop breakpoint —
  // `100dvh` minus everything the page stacks above the grid (top bar,
  // page padding, the back link, `PageHeading`, and the gaps between them),
  // floored at `26rem` so a very short viewport degrades to a normal page
  // scroll instead of an unusably squashed workspace. Kept identical on
  // both sides on purpose (see `sendTurn`'s composer requirement below) —
  // if you retune one, retune the other the same way.
  const WORKSPACE_HEIGHT = 'xl:h-[max(26rem,calc(100dvh-19rem))]';

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(24rem,1.3fr)]">
      <div className={`flex min-h-[50vh] flex-col ${WORKSPACE_HEIGHT}`}>
        <ScriptChatPanel
          turns={detail.turns}
          selectedTurnId={selectedTurnId}
          onSelectTurn={(id) => void selectTurn(id)}
          onSend={sendTurn}
          streaming={documentStreaming}
          liveText={firstDraftStreaming ? (createStream?.liveText ?? '') : stream.liveText}
          streamError={stream.error}
        />
      </div>
      {/* Fixed to the same height as the chat column (not just capped) so
          the composer on the left is always fully on screen without paging
          the whole browser window — the turn history and this panel are
          the two things with no natural length limit, so both need to be
          the ones that scroll internally instead. Only kicks in once the
          two-column layout itself does (`xl:`); below that both panels
          stack and the page scrolls normally like everywhere else. */}
      <div className={`rounded-[var(--radius-md)] border border-border bg-surface p-4 ${WORKSPACE_HEIGHT} xl:overflow-y-auto`}>
        {documentStreaming ? (
          <ScriptDocumentLoading label={t('generating')} hint={t('scriptGeneratingBody')} />
        ) : (
          <ScriptDocumentView
            document={viewedScript ?? detail.script}
            episodeId={episodeId}
            onLink={isViewingLatest ? (update) => void updateLink(update) : undefined}
            onSaveContent={isViewingLatest ? (next) => void saveContent(next) : undefined}
          />
        )}
      </div>
    </div>
  );
}
