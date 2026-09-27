'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { ErrorNotice } from '@/components/ui/primitives';
import type { ShortformProfile } from '@/lib/api/types';

import type { EditorActions } from '../actions';
import type {
  CanonicalDocument,
  EditCommand,
  ResolvedAsset,
  TimelineElement,
} from '../engine/ports';
import { TICKS_PER_SECOND } from '../engine/ports';
import { Preview } from '../preview';
import { Timeline } from '../timeline/timeline';
import { EditorHeader } from './editor-header';
import { MediaLibraryPanel } from './media-library-panel';
import { PropertiesPanel, type PropertiesTab } from './properties-panel';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from './resizable';
import { ShortcutsDialog } from './shortcuts-dialog';

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
 * The keyboard map, adapted from OpenCut's `use-keyboard-shortcuts` and
 * listed verbatim in `shortcuts-dialog.tsx`. Edit verbs are gated on
 * `disabled` (no write lease); transport and selection keys always work.
 */
function useEditorShortcuts(actions: EditorActions, disabled: boolean, onToggleHelp: () => void) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      const modifier = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();

      // Transport — never gated.
      if (event.code === 'Space' || (key === 'k' && !modifier)) {
        event.preventDefault();
        actions.togglePlay();
        return;
      }
      if (!modifier && (key === 'j' || key === 'l')) {
        event.preventDefault();
        actions.seekBy(key === 'j' ? -TICKS_PER_SECOND : TICKS_PER_SECOND);
        return;
      }
      if (key === 'arrowleft' || key === 'arrowright') {
        event.preventDefault();
        const direction = key === 'arrowleft' ? -1 : 1;
        if (event.shiftKey) actions.seekBy(direction * 5 * TICKS_PER_SECOND);
        else actions.stepFrames(direction);
        return;
      }
      if (key === 'home') {
        event.preventDefault();
        actions.goToStart();
        return;
      }
      if (key === 'end') {
        event.preventDefault();
        actions.goToEnd();
        return;
      }
      if (key === '?' || (event.shiftKey && key === '/')) {
        event.preventDefault();
        onToggleHelp();
        return;
      }

      // Selection — never gated either.
      if (modifier && key === 'a') {
        event.preventDefault();
        actions.selectAll();
        return;
      }
      if (key === 'escape') {
        actions.deselectAll();
        return;
      }
      if (!modifier && key === 'n') {
        event.preventDefault();
        actions.toggleSnapping();
        return;
      }

      if (disabled) return;

      if (modifier && key === 'z') {
        event.preventDefault();
        if (event.shiftKey) actions.redo();
        else actions.undo();
        return;
      }
      if (modifier && key === 'y') {
        event.preventDefault();
        actions.redo();
        return;
      }
      if (modifier && key === 'd') {
        event.preventDefault();
        actions.duplicateSelected();
        return;
      }
      if (modifier && key === 'c') {
        actions.copySelected();
        return;
      }
      if (modifier && key === 'v') {
        if (!actions.canPaste) return;
        event.preventDefault();
        actions.paste();
        return;
      }
      if (modifier) return;
      switch (key) {
        case 'delete':
        case 'backspace':
          event.preventDefault();
          actions.deleteSelected();
          return;
        case 's':
          event.preventDefault();
          actions.splitAtPlayhead();
          return;
        case 'w':
          event.preventDefault();
          actions.keepLeft();
          return;
        case 'q':
          event.preventDefault();
          actions.keepRight();
          return;
        case 'm':
          event.preventDefault();
          actions.toggleMarkerAtPlayhead();
          return;
        default:
          return;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [actions, disabled, onToggleHelp]);
}

/**
 * Adapted from OpenCut's `app/editor/[project_id]/page.tsx` `EditorLayout` —
 * the same nesting (a vertical group holding a horizontal 3-column region
 * above a full-width timeline), the same 25/50/25 + 50/50 defaults, and
 * `autoSaveId` so the user's panel sizes survive a reload — wired to
 * ZaoLang's own engine state instead of OpenCut's `useEditor`/
 * `usePanelStore`. `Onboarding`, `MigrationDialog` and
 * `ChangelogNotification` (OpenCut-account-specific) are not carried over.
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
  serverBusy,
  selected,
  selectedIds,
  caption,
  onCaptionChange,
  onApply,
  onRename,
  actions,
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
  onDropFiles,
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
  /** A server round-trip (save/restore) is in flight — only the panels that must see a settled head care. */
  serverBusy: boolean;
  selected: TimelineElement | undefined;
  selectedIds: string[];
  caption: string;
  onCaptionChange: (value: string) => void;
  onApply: (commands: EditCommand[]) => void;
  onRename: (name: string) => void;
  actions: EditorActions;
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
  onDropFiles: (files: File[], atTicks: number) => void;
}) {
  const t = useTranslations('editor');
  const [helpOpen, setHelpOpen] = useState(false);
  const [propertiesTab, setPropertiesTab] = useState<PropertiesTab>('element');
  const [exportRequestNonce, setExportRequestNonce] = useState(0);

  useEditorShortcuts(actions, disabled, () => setHelpOpen((open) => !open));

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <EditorHeader
        title={cutName}
        episodeId={episodeId}
        saveStatus={saveStatus}
        leaseExpiresAt={readonly ? null : leaseExpiresAt}
        disabled={disabled}
        onRename={onRename}
        onExport={() => {
          setPropertiesTab('document');
          setExportRequestNonce((n) => n + 1);
        }}
        onShowShortcuts={() => setHelpOpen(true)}
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
        <ResizablePanelGroup direction="vertical" autoSaveId="zaolang-studio-editor-v">
          <ResizablePanel defaultSize={50} minSize={30} className="min-h-0 min-w-0 overflow-hidden">
            <ResizablePanelGroup direction="horizontal" autoSaveId="zaolang-studio-editor-h">
              <ResizablePanel
                defaultSize={25}
                minSize={15}
                maxSize={40}
                className="min-h-0 min-w-0 overflow-hidden"
              >
                <MediaLibraryPanel
                  disabled={disabled}
                  onApply={onApply}
                  caption={caption}
                  onCaptionChange={onCaptionChange}
                />
              </ResizablePanel>
              <ResizableHandle />
              <ResizablePanel
                defaultSize={50}
                minSize={30}
                className="min-h-0 min-w-0 overflow-hidden"
              >
                <div className="flex h-full min-h-0 flex-col overflow-hidden">
                  <Preview
                    document={document}
                    assets={assets}
                    durationTicks={durationTicks}
                    title={cutName}
                    selected={selected}
                    disabled={disabled}
                    actions={actions}
                    onApply={onApply}
                  />
                </div>
              </ResizablePanel>
              <ResizableHandle />
              <ResizablePanel
                defaultSize={25}
                minSize={15}
                maxSize={40}
                className="min-h-0 min-w-0 overflow-hidden"
              >
                <PropertiesPanel
                  document={document}
                  assets={assets}
                  durationTicks={durationTicks}
                  revisionId={revisionId}
                  syncNonce={syncNonce}
                  draftId={draftId}
                  disabled={disabled}
                  serverBusy={serverBusy}
                  profiles={profiles}
                  defaultProfile={defaultProfile}
                  selected={selected}
                  selectedIds={selectedIds}
                  actions={actions}
                  cutId={cutId}
                  leaseId={leaseId}
                  leaseToken={leaseToken}
                  onApply={onApply}
                  onPlanApplied={onPlanApplied}
                  onRestore={onRestore}
                  tab={propertiesTab}
                  onTabChange={setPropertiesTab}
                  exportRequestNonce={exportRequestNonce}
                />
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel
            defaultSize={50}
            minSize={20}
            maxSize={70}
            className="min-h-0 min-w-0 overflow-hidden"
          >
            <Timeline
              document={document}
              assets={assets}
              durationTicks={durationTicks}
              disabled={disabled}
              actions={actions}
              onCommand={onApply}
              onDropFiles={onDropFiles}
            />
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
      <ShortcutsDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}
