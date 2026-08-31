'use client';

import { useTranslations } from 'next-intl';
import { useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { ErrorNotice } from '@/components/ui/primitives';
import type { ShortformProfile } from '@/lib/api/types';

import type { CanonicalDocument, EditCommand, ResolvedAsset, TimelineElement } from '../engine/ports';
import { TICKS_PER_SECOND } from '../engine/ports';
import { Preview } from '../preview';
import { useEditorUi } from '../store';
import { Timeline } from '../timeline';
import { EditorHeader } from './editor-header';
import { MediaLibraryPanel } from './media-library-panel';
import { PropertiesPanel } from './properties-panel';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from './resizable';

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT' ||
    target.isContentEditable
  );
}

/**
 * Adapted from OpenCut's `app/editor/[project_id]/page.tsx` `EditorLayout` —
 * the same nesting (a vertical group holding a horizontal 3-column region
 * above a full-width timeline) — wired to ZaoLang's own engine state
 * instead of OpenCut's `useEditor`/`usePanelStore`. `Onboarding`,
 * `MigrationDialog`, and `ChangelogNotification` (OpenCut-account-specific)
 * are not carried over.
 */
export function StudioShell({
  cutName,
  episodeId,
  saveStatus,
  readonly,
  heldByOther,
  reclaiming,
  onReclaim,
  leaseExpiresAt,
  document,
  assets,
  durationTicks,
  disabled,
  selected,
  selectedIds,
  caption,
  onCaptionChange,
  onSelect,
  onApply,
  onDeleteSelected,
  onSplitAtPlayhead,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  revisionId,
  syncNonce,
  draftId,
  profiles,
  defaultProfile,
  cutId,
  leaseId,
  leaseToken,
  onPlanApplied,
  onRestore,
}: {
  cutName: string;
  episodeId: string | null;
  saveStatus: 'idle' | 'saving' | 'saved';
  readonly: boolean;
  heldByOther: boolean;
  reclaiming: boolean;
  onReclaim: () => void;
  leaseExpiresAt: string | null;
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  durationTicks: number;
  disabled: boolean;
  selected: TimelineElement | undefined;
  selectedIds: string[];
  caption: string;
  onCaptionChange: (value: string) => void;
  onSelect: (element: TimelineElement) => void;
  onApply: (commands: EditCommand[]) => void;
  onDeleteSelected: () => void;
  onSplitAtPlayhead: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  revisionId: string | null;
  syncNonce: number;
  draftId: string | null;
  profiles: ShortformProfile[];
  defaultProfile: string | null;
  cutId: string;
  leaseId: string | null;
  leaseToken: string | null;
  onPlanApplied: () => void;
  onRestore: (revisionId: string) => void;
}) {
  const t = useTranslations('editor');
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const setPlayhead = useEditorUi((state) => state.setPlayhead);

  // Walkthrough finding: every edit required reaching for the mouse (no
  // Delete/split/frame-step shortcuts), which made fine-grained trimming
  // and cleanup noticeably slower than a desktop NLE. Space/play is handled
  // locally inside `Preview` (it owns the playing state); this covers the
  // shortcuts that operate on the shared selection/playhead instead.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (disabled || isTypingTarget(event.target)) return;
      const modifier = event.metaKey || event.ctrlKey;
      if (modifier && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) onRedo();
        else onUndo();
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (selectedIds.length === 0) return;
        event.preventDefault();
        onDeleteSelected();
      } else if (event.key === 's' || event.key === 'S') {
        if (!selected) return;
        event.preventDefault();
        onSplitAtPlayhead();
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        const frameTicks = Math.max(
          1,
          Math.round((TICKS_PER_SECOND * document.canvas.fps_den) / document.canvas.fps_num),
        );
        const delta = event.key === 'ArrowLeft' ? -frameTicks : frameTicks;
        setPlayhead(Math.max(0, Math.min(durationTicks, playheadTicks + delta)));
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [
    disabled,
    selectedIds,
    selected,
    onDeleteSelected,
    onSplitAtPlayhead,
    onUndo,
    onRedo,
    document.canvas.fps_den,
    document.canvas.fps_num,
    durationTicks,
    playheadTicks,
    setPlayhead,
  ]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <EditorHeader
        title={cutName}
        episodeId={episodeId}
        saveStatus={saveStatus}
        leaseExpiresAt={readonly ? null : leaseExpiresAt}
      />
      {readonly ? (
        <div className="border-b border-border">
          <ErrorNotice
            title={t('readonlyLease')}
            detail={heldByOther ? t('leaseLost') : t('leaseNotReady')}
            action={
              <Button size="sm" variant="secondary" loading={reclaiming} onClick={onReclaim}>
                {t('reclaimLease')}
              </Button>
            }
          />
        </div>
      ) : null}
      <div className="min-h-0 flex-1">
        <ResizablePanelGroup direction="vertical">
          <ResizablePanel defaultSize={58} minSize={32} className="min-h-0 min-w-0 overflow-hidden">
            <ResizablePanelGroup direction="horizontal">
              <ResizablePanel defaultSize={22} minSize={15} maxSize={40} className="min-h-0 min-w-0 overflow-hidden">
                <MediaLibraryPanel
                  disabled={disabled}
                  onApply={onApply}
                  caption={caption}
                  onCaptionChange={onCaptionChange}
                />
              </ResizablePanel>
              <ResizableHandle />
              <ResizablePanel defaultSize={53} minSize={30} className="min-h-0 min-w-0 overflow-hidden">
                <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden p-3">
                  <Preview
                    document={document}
                    assets={assets}
                    durationTicks={durationTicks}
                    title={cutName}
                    selected={selected}
                    disabled={disabled}
                    onApply={onApply}
                  />
                  <p className="shrink-0 text-xs text-muted">
                    {t('canvasLabel')} · {document.canvas.width}×{document.canvas.height} ·{' '}
                    {t('durationLabel', {
                      seconds: (Math.max(durationTicks, 0) / TICKS_PER_SECOND).toFixed(1),
                    })}
                  </p>
                </div>
              </ResizablePanel>
              <ResizableHandle />
              <ResizablePanel defaultSize={25} minSize={15} maxSize={40} className="min-h-0 min-w-0 overflow-hidden">
                <PropertiesPanel
                  document={document}
                  assets={assets}
                  durationTicks={durationTicks}
                  revisionId={revisionId}
                  syncNonce={syncNonce}
                  draftId={draftId}
                  disabled={disabled}
                  profiles={profiles}
                  defaultProfile={defaultProfile}
                  selected={selected}
                  cutId={cutId}
                  leaseId={leaseId}
                  leaseToken={leaseToken}
                  onApply={onApply}
                  onPlanApplied={onPlanApplied}
                  onRestore={onRestore}
                />
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize={42} minSize={24} maxSize={60} className="min-h-0 min-w-0 overflow-hidden">
            <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden p-3">
              <div className="flex shrink-0 flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={disabled || !canUndo}
                  onClick={onUndo}
                  title={t('undoShortcutHint')}
                >
                  {t('undo')}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={disabled || !canRedo}
                  onClick={onRedo}
                  title={t('redoShortcutHint')}
                >
                  {t('redo')}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={disabled || selectedIds.length === 0}
                  onClick={onDeleteSelected}
                  title={t('deleteSelectedShortcutHint')}
                >
                  {t('deleteSelected')}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={disabled || !selected}
                  onClick={onSplitAtPlayhead}
                  title={t('splitAtPlayheadShortcutHint')}
                >
                  {t('splitAtPlayhead')}
                </Button>
              </div>
              <Timeline
                document={document}
                assets={assets}
                durationTicks={durationTicks || TICKS_PER_SECOND}
                disabled={disabled}
                playheadLabel={t('playhead')}
                onSelect={onSelect}
                onCommand={onApply}
              />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </div>
  );
}
