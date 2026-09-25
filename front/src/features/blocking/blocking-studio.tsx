'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { IconVideo, IconWand } from '@/components/ui/icons';
import { Link } from '@/i18n/navigation';
import { EmptyState } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import * as scriptApi from '@/features/script/api';
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
import { applyEdit, type BlockingEdit } from './edits';
import type { BlockingEditor, EditorSelection, GizmoMode } from './engine/editor';
import type { BlockingPlayer, CastLabel, ViewMode } from './engine/player';
import { castColor } from './palette';
import type { AspectRatio, BlockingState } from './types';
import { BlockingVideoDialog } from './blocking-video-dialog';
import { ShotPicker } from './shot-picker';
import { useBlockingVideo, type SegmentVideoItem } from './use-blocking-video';
import { planSegmentVideos } from './video-plan';
import { useBlockingSave } from './use-blocking-save';
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
  const [gizmoMode, setGizmoMode] = useState<GizmoMode>('translate');
  const [selection, setSelection] = useState<EditorSelection>(null);
  const editorRef = useRef<BlockingEditor | null>(null);
  const stream = useBlockingStream();
  const video = useBlockingVideo(episodeId);
  const [videoKeys, setVideoKeys] = useState<string[] | null>(null);
  const characters = useResource<Character[]>('/v1/characters');

  const reload = useCallback(async () => {
    try {
      const next = await scriptApi.getScript(episodeId);
      setDetail(next);
      setState(next.blocking ?? EMPTY_STATE);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('unavailable'), 'error');
    }
  }, [episodeId, notify, t]);

  const save = useBlockingSave({
    episodeId,
    versionNo: state.version_no,
    onSaved: useCallback((next: BlockingState) => setState(next), []),
    onConflict: useCallback(() => {
      notify(t('conflictReloaded'), 'error');
      void reload();
    }, [notify, reload, t]),
    onError: useCallback((message: string) => notify(message, 'error'), [notify]),
  });

  // The latest state for event handlers — an edit must apply on top of the
  // previous edit even before React has re-rendered with it.
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  const { schedule } = save;
  const edit = useCallback(
    (change: BlockingEdit) => {
      const current = stateRef.current;
      if (!current.document) return;
      const next = { ...current, document: applyEdit(current.document, change) };
      stateRef.current = next;
      setState(next);
      schedule(next.document);
    },
    [schedule],
  );

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
    void stream.run({ kind: 'turn', episodeId, message, currentScript: detail.script }, (result) =>
      applyComplete(result, message),
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

  const selectionLabel = (current: EditorSelection): string | null => {
    if (!current || !document) return null;
    if (current.kind === 'camera') return t('selectedCamera');
    if (current.kind === 'cast') {
      return document.cast?.find((member) => member.id === current.castId)?.name ?? null;
    }
    const prop = document.sets
      ?.find((set) => set.id === current.setId)
      ?.props?.find((item) => item.id === current.propId);
    return prop ? prop.label || prop.id : null;
  };

  const videoPlans = useMemo(
    () => (document && videoKeys ? planSegmentVideos(document, detail.script, videoKeys) : []),
    [document, detail.script, videoKeys],
  );
  const openVideo = (scope: 'segment' | 'all') => {
    if (!document) return;
    const keys =
      scope === 'all'
        ? (document.segments ?? []).map((segment) => segment.key)
        : [player?.lastFrame?.segment.key].filter((key): key is string => Boolean(key));
    if (keys.length > 0) setVideoKeys(keys);
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
            editable={Boolean(document) && !busy}
            gizmoMode={gizmoMode}
            onEdit={edit}
            onSelect={setSelection}
            onEditor={(instance) => {
              editorRef.current = instance;
            }}
            loadingLabel={t('loadingEngine')}
            errorLabel={t('engineError')}
          >
            {view === 'free' && document && !busy ? (
              <EditToolbar
                mode={gizmoMode}
                onModeChange={setGizmoMode}
                selection={selection}
                selectionLabel={selectionLabel(selection)}
                onCapture={() => {
                  const change = editorRef.current?.captureFreeView();
                  if (change) edit(change);
                }}
              />
            ) : null}
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
            saveStatus={save.status}
          />
          <SegmentScrubber
            player={player}
            timeline={timeline}
            staleKeys={staleKeys}
            disabled={busy}
          />
          <SegmentInspector player={player} document={document} />
          <ShotPicker player={player} document={document} disabled={busy} onEdit={edit} />
          {document ? (
            <VideoActions
              episodeId={episodeId}
              disabled={busy || video.running}
              stale={state.stale}
              items={video.items}
              running={video.running}
              onGenerate={openVideo}
              onCancel={video.cancel}
            />
          ) : null}
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
      {videoKeys && document ? (
        <BlockingVideoDialog
          plans={videoPlans}
          onClose={() => setVideoKeys(null)}
          onConfirm={(params, unitCredits) => {
            setVideoKeys(null);
            player?.pause();
            void video.start(document, videoPlans, params, unitCredits);
          }}
        />
      ) : null}
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

function EditToolbar({
  mode,
  onModeChange,
  selection,
  selectionLabel,
  onCapture,
}: {
  mode: GizmoMode;
  onModeChange: (mode: GizmoMode) => void;
  selection: EditorSelection;
  selectionLabel: string | null;
  onCapture: () => void;
}) {
  const t = useTranslations('blockingStudio');
  const modes: GizmoMode[] =
    selection?.kind === 'camera'
      ? ['translate']
      : selection?.kind === 'cast'
        ? ['translate', 'rotate']
        : ['translate', 'rotate', 'scale'];
  return (
    <div className="absolute inset-x-2 top-2 flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface/90 p-1.5 text-xs shadow-card">
      <div role="radiogroup" aria-label={t('gizmoLabel')} className="flex gap-1">
        {modes.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={mode === option}
            onClick={() => onModeChange(option)}
            className={
              mode === option
                ? 'h-8 rounded-[calc(var(--radius-sm)-2px)] bg-primary/15 px-2.5 font-medium text-text'
                : 'h-8 rounded-[calc(var(--radius-sm)-2px)] px-2.5 text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-focus'
            }
          >
            {t(`gizmo.${option}`)}
          </button>
        ))}
      </div>
      <span className="min-w-0 flex-1 truncate text-muted">
        {selectionLabel ? t('selected', { name: selectionLabel }) : t('editHint')}
      </span>
      <Button size="sm" variant="secondary" onClick={onCapture}>
        {t('captureView')}
      </Button>
    </div>
  );
}

function VideoActions({
  episodeId,
  disabled,
  stale,
  items,
  running,
  onGenerate,
  onCancel,
}: {
  episodeId: string;
  disabled: boolean;
  stale: boolean;
  items: SegmentVideoItem[];
  running: boolean;
  onGenerate: (scope: 'segment' | 'all') => void;
  onCancel: () => void;
}) {
  const t = useTranslations('blockingStudio');
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          icon={<IconVideo className="size-4" />}
          disabled={disabled}
          onClick={() => onGenerate('segment')}
        >
          {t('videoSegment')}
        </Button>
        <Button size="sm" variant="secondary" disabled={disabled} onClick={() => onGenerate('all')}>
          {t('videoAll')}
        </Button>
        {running ? (
          <Button size="sm" variant="ghost" onClick={onCancel}>
            {t('videoStop')}
          </Button>
        ) : null}
        <span className="text-xs text-muted">{stale ? t('videoStaleHint') : t('videoHint')}</span>
      </div>
      {items.length > 0 ? (
        <ul className="flex max-h-28 flex-col gap-1 overflow-y-auto text-xs" aria-live="polite">
          {items.map((item) => (
            <li key={item.key} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-text">{item.key}</span>
              <span className={item.status === 'failed' ? 'text-danger' : 'text-muted'}>
                {item.status === 'rendering'
                  ? t('videoStatus.rendering', { percent: Math.round(item.progress * 100) })
                  : t(`videoStatus.${item.status}`)}
              </span>
              {item.status === 'succeeded' && item.draftId ? (
                <Link
                  className="text-primary hover:underline"
                  href={`/create/script/${episodeId}/clip?${new URLSearchParams({
                    key: item.key,
                    draftId: item.draftId,
                  }).toString()}`}
                >
                  {t('videoOpen')}
                </Link>
              ) : null}
              {item.status === 'failed' && item.error ? (
                <span className="max-w-48 truncate text-danger" title={item.error}>
                  {item.error}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
