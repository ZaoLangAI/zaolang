'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { ErrorNotice } from '@/components/ui/primitives';
import type { ShortformProfile } from '@/lib/api/types';

import type { CanonicalDocument, EditCommand, ResolvedAsset, TimelineElement } from '../engine/ports';
import { TICKS_PER_SECOND } from '../engine/ports';
import { Preview } from '../preview';
import { Timeline } from '../timeline';
import { EditorHeader } from './editor-header';
import { MediaLibraryPanel } from './media-library-panel';
import { PropertiesPanel } from './properties-panel';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from './resizable';

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
  readonly,
  heldByOther,
  reclaiming,
  onReclaim,
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
  revisionId,
  draftId,
  profiles,
  cutId,
  leaseId,
  leaseToken,
  onPlanApplied,
  onRestore,
}: {
  cutName: string;
  episodeId: string | null;
  readonly: boolean;
  heldByOther: boolean;
  reclaiming: boolean;
  onReclaim: () => void;
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
  revisionId: string | null;
  draftId: string | null;
  profiles: ShortformProfile[];
  cutId: string;
  leaseId: string | null;
  leaseToken: string | null;
  onPlanApplied: () => void;
  onRestore: (revisionId: string) => void;
}) {
  const t = useTranslations('editor');

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <EditorHeader title={cutName} episodeId={episodeId} />
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
                  draftId={draftId}
                  disabled={disabled}
                  profiles={profiles}
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
                  disabled={disabled || selectedIds.length === 0}
                  onClick={onDeleteSelected}
                >
                  {t('deleteSelected')}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={disabled || !selected}
                  onClick={onSplitAtPlayhead}
                >
                  {t('splitAtPlayhead')}
                </Button>
              </div>
              <Timeline
                document={document}
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
