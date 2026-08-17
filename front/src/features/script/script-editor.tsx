'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { EmptyState, ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { Link } from '@/i18n/navigation';
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
export function ScriptEditor({ episodeId }: { episodeId: string }) {
  const t = useTranslations('scriptStudio');
  const { notify } = useToast();
  const [detail, setDetail] = useState<ScriptDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [viewedScript, setViewedScript] = useState<ScriptDocument | null>(null);
  const [firstDraftError, setFirstDraftError] = useState<string | null>(null);
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
            onLink={isViewingLatest ? (update) => void updateLink(update) : undefined}
          />
        )}
      </div>
    </div>
  );
}
