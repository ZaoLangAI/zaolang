'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { IconMessage, IconVideo, IconWand } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { Link } from '@/i18n/navigation';
import { cn } from '@/lib/cn';
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
import { SegmentScrubber, StaleBanner, TransportBar } from './blocking-controls';
import { BlockingSettingsDialog } from './blocking-settings-dialog';
import { BlockingViewport } from './blocking-viewport';
import { compileBlocking } from './compiler/compile';
import { applyEdit, type BlockingEdit } from './edits';
import type { BlockingEditor, EditorSelection, GizmoMode } from './engine/editor';
import type { BlockingPlayer, CastLabel, ViewMode } from './engine/player';
import { castColor } from './palette';
import type { AspectRatio, BlockingState } from './types';
import { BlockingVideoDialog } from './blocking-video-dialog';
import { ShotPanel } from './shot-panel';
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

type PanelTab = 'chat' | 'shots' | 'video';

/**
 * The 纯白膜创作 workspace. Desktop: the live 3D blockout fills the left
 * column (viewport, one slim transport row, the scrubber) and a tabbed side
 * panel holds the chat (对话), the playing segment's shots (镜头) and video
 * generation (生成) — nothing is stacked under the viewport to squeeze it.
 * Phones: the same pieces stacked, viewport first.
 *
 * A chat message can rewrite the script *and* re-stage the blockout in one
 * turn; the script page sees these turns in its own history (tagged 白膜).
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
  const [tab, setTab] = useState<PanelTab>('chat');
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
  const videoRunning = video.items.filter(
    (item) => item.status !== 'succeeded' && item.status !== 'failed',
  ).length;

  const tabs: { id: PanelTab; label: string; badge?: number }[] = [
    { id: 'chat', label: t('tabChat') },
    { id: 'shots', label: t('tabShots') },
    { id: 'video', label: t('tabVideo'), badge: videoRunning || undefined },
  ];

  return (
    <>
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,25rem)] lg:gap-4">
        <section
          aria-label={t('viewportLabel')}
          className="flex h-[62dvh] min-h-[22rem] min-w-0 flex-col gap-2 lg:h-auto lg:min-h-0"
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
        </section>

        <aside className="flex h-[75dvh] min-h-[26rem] min-w-0 flex-col overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface lg:h-auto lg:min-h-0">
          <div
            role="tablist"
            aria-label={t('panelLabel')}
            className="flex shrink-0 border-b border-border"
          >
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                id={`blocking-tab-${item.id}`}
                aria-selected={tab === item.id}
                aria-controls={`blocking-panel-${item.id}`}
                onClick={() => setTab(item.id)}
                className={cn(
                  'relative flex h-11 flex-1 items-center justify-center gap-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
                  tab === item.id ? 'text-text' : 'text-muted hover:text-text',
                )}
              >
                {item.label}
                {item.badge ? (
                  <span className="rounded-full bg-primary px-1.5 text-[10px] leading-4 text-on-primary">
                    {item.badge}
                  </span>
                ) : null}
                {tab === item.id ? (
                  <span
                    aria-hidden
                    className="absolute inset-x-4 bottom-0 h-0.5 rounded-full bg-primary"
                  />
                ) : null}
              </button>
            ))}
          </div>
          <div
            role="tabpanel"
            id={`blocking-panel-${tab}`}
            aria-labelledby={`blocking-tab-${tab}`}
            className={cn(
              'min-h-0 flex-1 p-3',
              tab === 'chat' ? 'flex flex-col' : 'overflow-y-auto',
            )}
          >
            {tab === 'chat' ? (
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
            ) : null}
            {tab === 'shots' ? (
              <ShotPanel player={player} document={document} disabled={busy} onEdit={edit} />
            ) : null}
            {tab === 'video' ? (
              document ? (
                <VideoActions
                  episodeId={episodeId}
                  disabled={busy || video.running}
                  stale={state.stale}
                  items={video.items}
                  running={video.running}
                  onGenerate={openVideo}
                  onCancel={video.cancel}
                />
              ) : (
                <p className="text-sm text-muted">{t('emptyHint')}</p>
              )
            ) : null}
          </div>
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
    <div className="absolute left-2 top-2 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface/90 p-1.5 text-xs shadow-card">
      <div role="radiogroup" aria-label={t('gizmoLabel')} className="flex gap-1">
        {modes.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={mode === option}
            onClick={() => onModeChange(option)}
            className={cn(
              'h-8 rounded-[calc(var(--radius-sm)-2px)] px-2.5 focus-visible:outline-2 focus-visible:outline-focus',
              mode === option
                ? 'bg-primary/15 font-medium text-text'
                : 'text-muted hover:text-text',
            )}
          >
            {t(`gizmo.${option}`)}
          </button>
        ))}
      </div>
      <span className="hidden min-w-0 max-w-56 truncate text-muted sm:inline">
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
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">{stale ? t('videoStaleHint') : t('videoHint')}</p>
      <div className="grid gap-2">
        <Button
          icon={<IconVideo className="size-4" />}
          disabled={disabled}
          onClick={() => onGenerate('segment')}
        >
          {t('videoSegment')}
        </Button>
        <Button variant="secondary" disabled={disabled} onClick={() => onGenerate('all')}>
          {t('videoAll')}
        </Button>
        {running ? (
          <Button variant="ghost" onClick={onCancel}>
            {t('videoStop')}
          </Button>
        ) : null}
      </div>
      {items.length > 0 ? (
        <ul className="flex flex-col gap-2 text-sm" aria-live="polite">
          {items.map((item) => (
            <li
              key={item.key}
              className="flex flex-col gap-1 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-text">{item.key}</span>
                {item.status === 'succeeded' && item.draftId ? (
                  <Link
                    className="shrink-0 text-primary hover:underline"
                    href={`/create/script/${episodeId}/clip?${new URLSearchParams({
                      key: item.key,
                      draftId: item.draftId,
                    }).toString()}`}
                  >
                    {t('videoOpen')}
                  </Link>
                ) : null}
              </div>
              <span
                className={cn('text-xs', item.status === 'failed' ? 'text-danger' : 'text-muted')}
              >
                {item.status === 'rendering'
                  ? t('videoStatus.rendering', { percent: Math.round(item.progress * 100) })
                  : t(`videoStatus.${item.status}`)}
                {item.status === 'failed' && item.error ? ` · ${item.error}` : ''}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="flex items-center gap-2 text-xs text-muted">
          <IconMessage className="size-4" />
          {t('videoEmpty')}
        </p>
      )}
    </div>
  );
}
