'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { IconWand } from '@/components/ui/icons';
import { EmptyState } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import type { ScriptDetail } from '@/features/script/api';
import { ScriptChatPanel } from '@/features/script/script-chat-panel';
import { extractStreamingSummary } from '@/features/script/stream-preview';
import { isApiError } from '@/lib/api/errors';
import type { Character } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

import * as blockingApi from './api';
import type { BlockingPhase, BlockingTurnCompleteEvent } from './api';
import { SegmentInspector, SegmentScrubber, StaleBanner, TransportBar } from './blocking-controls';
import { BlockingSettingsDialog } from './blocking-settings-dialog';
import { BlockingViewport } from './blocking-viewport';
import { compileBlocking } from './compiler/compile';
import type { BlockingPlayer, CastLabel, ViewMode } from './engine/player';
import { castColor } from './palette';
import type { AspectRatio, BlockingState } from './types';
import { useBlockingStream } from './use-blocking-stream';

const EMPTY_STATE: BlockingState = {
  document: null,
  version_no: 0,
  stale: false,
  stale_segment_keys: [],
  duration_warning: null,
  target_duration_seconds: null,
  default_target_duration_seconds: 0,
};

/** The first reference image of a linked library character — what the cast
 * tag over each mannequin shows. */
function characterImage(character: Character | undefined): string | null {
  const assets = character?.reference_assets ?? [];
  const front = assets.find((asset) => asset.view === 'front' && asset.url);
  return front?.url ?? assets.find((asset) => asset.url)?.url ?? null;
}

/**
 * The 纯白膜创作 workspace: the live 3D blockout on the left two-thirds (with
 * transport, a segment scrubber and the playing segment's shot), and the
 * same conversational panel as 文案创作 on the right. A message here can
 * rewrite the script *and* re-stage the blockout in one turn; the script
 * page sees these turns in its own history (tagged 白膜).
 */
export function BlockingStudio({
  episodeId,
  initial,
}: {
  episodeId: string;
  initial: ScriptDetail;
}) {
  const t = useTranslations('blockingStudio');
  const { notify } = useToast();
  const [detail, setDetail] = useState<ScriptDetail>(initial);
  const [state, setState] = useState<BlockingState>(initial.blocking ?? EMPTY_STATE);
  const [player, setPlayer] = useState<BlockingPlayer | null>(null);
  const [view, setView] = useState<ViewMode>('director');
  const [labelsVisible, setLabelsVisible] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const stream = useBlockingStream();
  const characters = useResource<Character[]>('/v1/characters');

  const document = state.document ?? null;
  const aspect: AspectRatio = document?.aspect_ratio ?? '9:16';
  const timeline = useMemo(() => (document ? compileBlocking(document) : null), [document]);
  const staleKeys = useMemo(() => new Set(state.stale_segment_keys ?? []), [state]);

  const labels = useMemo(() => {
    const byId = new Map((characters.data ?? []).map((character) => [character.id, character]));
    const result: Record<string, CastLabel> = {};
    for (const member of document?.cast ?? []) {
      result[member.id] = {
        name: member.name,
        colorCss: castColor(member.color_index).css,
        imageUrl: member.character_ref_id
          ? characterImage(byId.get(member.character_ref_id))
          : null,
      };
    }
    return result;
  }, [characters.data, document]);

  const applyComplete = useCallback(
    (result: BlockingTurnCompleteEvent, message: string | null) => {
      setState(result.blocking);
      setDetail((current) => ({
        ...current,
        script: result.script,
        blocking: result.blocking,
        turns:
          result.turn_id && message
            ? [
                ...current.turns,
                {
                  id: result.turn_id,
                  turn_no: result.turn_no,
                  user_message: message,
                  summary: result.summary,
                  referenced_skill_ids: [],
                  created_at: new Date().toISOString(),
                  thinking: result.thinking,
                  origin: 'blocking',
                },
              ]
            : current.turns,
      }));
      if (result.script_changed) notify(t('scriptSynced'), 'success');
      if (result.degraded) notify(t('degraded'), 'error');
      if (result.blocking.duration_warning) notify(result.blocking.duration_warning, 'error');
    },
    [notify, t],
  );

  const sendTurn = (message: string) => {
    player?.pause();
    void stream.run(
      { kind: 'turn', episodeId, message, currentScript: detail.script },
      (result) => applyComplete(result, message),
    );
  };

  const rebuild = () => {
    player?.pause();
    void stream.run({ kind: 'rebuild', episodeId }, (result) => applyComplete(result, null));
  };

  const saveSettings = async (input: { targetSeconds: number | null; aspect: AspectRatio }) => {
    setSavingSettings(true);
    try {
      const next = await blockingApi.updateBlockingSettings(episodeId, {
        targetDurationSeconds: input.targetSeconds,
        aspectRatio: input.aspect,
        baseVersionNo: state.version_no,
      });
      setState(next);
      setSettingsOpen(false);
      if (next.duration_warning) notify(next.duration_warning, 'error');
    } catch (error) {
      const message = !isApiError(error)
        ? t('unavailable')
        : error.status === 409
          ? t('conflict')
          : error.message;
      notify(message, 'error');
    } finally {
      setSavingSettings(false);
    }
  };

  const phaseLabel = (phase: BlockingPhase | null) =>
    phase ? t(`phase.${phase}`) : t('phase.route');
  const busy = stream.streaming;
  const PANEL_HEIGHT = 'md:h-[max(34rem,calc(100dvh-13rem))]';

  return (
    <>
      <div className="md:hidden">
        <EmptyState title={t('gateTitle')} description={t('gateHint')} />
      </div>
      <div className="hidden gap-4 md:grid lg:grid-cols-[minmax(0,2fr)_minmax(20rem,1fr)]">
        <section
          aria-label={t('viewportLabel')}
          className={`flex min-h-[32rem] flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3 ${PANEL_HEIGHT}`}
        >
          {state.stale && document ? (
            <StaleBanner
              count={state.stale_segment_keys?.length ?? 0}
              onRebuild={rebuild}
              disabled={busy}
            />
          ) : null}
          <BlockingViewport
            document={document}
            labels={labels}
            aspect={aspect}
            view={view}
            onPlayer={setPlayer}
            loadingLabel={t('loadingEngine')}
            errorLabel={t('engineError')}
          >
            {!document && !busy ? (
              <div className="absolute inset-0 grid place-items-center bg-surface/85 p-6">
                <div className="flex max-w-sm flex-col items-center gap-3 text-center">
                  <p className="text-base font-semibold text-text">{t('emptyTitle')}</p>
                  <p className="text-sm text-muted">{t('emptyHint')}</p>
                  <Button icon={<IconWand className="size-4" />} onClick={rebuild}>
                    {t('build')}
                  </Button>
                </div>
              </div>
            ) : null}
            {busy ? (
              <div
                role="status"
                className="absolute inset-x-3 bottom-3 flex items-start gap-3 rounded-[var(--radius-sm)] border border-border bg-surface/90 p-3 text-sm shadow-raised"
              >
                <Spinner />
                <div className="min-w-0">
                  <p className="font-medium text-text">{phaseLabel(stream.phase)}</p>
                  <p className="line-clamp-2 text-xs text-muted">
                    {extractStreamingSummary(stream.liveText)}
                  </p>
                </div>
              </div>
            ) : null}
          </BlockingViewport>
          <TransportBar
            player={player}
            duration={timeline?.duration ?? 0}
            view={view}
            onViewChange={setView}
            labelsVisible={labelsVisible}
            onLabelsChange={(visible) => {
              setLabelsVisible(visible);
              player?.setLabels(visible);
            }}
            onOpenSettings={() => setSettingsOpen(true)}
            disabled={!document || busy}
          />
          <SegmentScrubber
            player={player}
            timeline={timeline}
            staleKeys={staleKeys}
            disabled={busy}
          />
          <SegmentInspector player={player} document={document} />
        </section>

        <aside className={`flex min-h-[28rem] flex-col ${PANEL_HEIGHT}`}>
          <ScriptChatPanel
            turns={detail.turns}
            selectedTurnId={null}
            onSend={(message) => sendTurn(message)}
            streaming={busy}
            liveText={stream.liveText}
            liveThinking={stream.liveThinking}
            streamError={stream.error}
            allowSkillMentions={false}
            placeholder={t('placeholder')}
            emptyHint={t('chatEmpty')}
            liveLabel={phaseLabel(stream.phase)}
            liveBodyPlaceholder={t('bodyPlaceholder')}
          />
        </aside>
      </div>
      {settingsOpen ? (
        <BlockingSettingsDialog
          open
          onClose={() => setSettingsOpen(false)}
          targetSeconds={state.target_duration_seconds ?? null}
          defaultTargetSeconds={state.default_target_duration_seconds ?? 0}
          aspect={aspect}
          saving={savingSettings}
          onSave={(input) => void saveSettings(input)}
        />
      ) : null}
    </>
  );
}
