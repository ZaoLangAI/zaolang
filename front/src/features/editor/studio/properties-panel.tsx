'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { CollapsibleSection } from '@/components/studio/collapsible-section';
import type { ShortformProfile } from '@/lib/api/types';

import { CanvasPanel } from '../canvas-panel';
import { CaptionBatchPanel } from '../caption-batch-panel';
import { ClipAdjustControls } from '../clip-adjust-controls';
import { EditPlanPanel } from '../edit-plan-panel';
import type { CanonicalDocument, EditCommand, ResolvedAsset, TimelineElement } from '../engine/ports';
import { EffectsMaskControls } from '../effects-mask-controls';
import { ExportPanel } from '../export-panel';
import { HistoryPanel } from '../history-panel';
import { KeyframeControls } from '../keyframe-controls';
import { TransitionControls } from '../transition-controls';

/**
 * Adapted from OpenCut's `components/editor/panels/properties/index.tsx` —
 * same "empty state, or the selected element's controls" shell — but
 * without its icon-tab-bar + type registry: this editor has exactly one
 * selectable element type (a clip, with volume/speed), so a full registry
 * would be machinery with nothing to switch between. `CanvasPanel` and
 * `ExportPanel` are document-level (not selection-scoped); they sit in
 * collapsed sections so a selected clip's controls stay reachable.
 */
export function PropertiesPanel({
  document,
  assets,
  durationTicks,
  revisionId,
  syncNonce,
  draftId,
  disabled,
  profiles,
  defaultProfile,
  selected,
  cutId,
  leaseId,
  leaseToken,
  onApply,
  onPlanApplied,
  onRestore,
}: {
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  durationTicks: number;
  revisionId: string | null;
  syncNonce: number;
  draftId: string | null;
  disabled: boolean;
  profiles: ShortformProfile[];
  defaultProfile: string | null;
  selected: TimelineElement | undefined;
  cutId: string;
  leaseId: string | null;
  leaseToken: string | null;
  onApply: (commands: EditCommand[]) => void;
  onPlanApplied: () => void;
  onRestore: (revisionId: string) => void;
}) {
  const t = useTranslations('editor');
  // Walkthrough finding: five stacked `CollapsibleSection`s meant the
  // document-level ones (export/history/canvas/AI plan) were always a long
  // scroll below whichever clip's properties were open. Splitting into two
  // top-level tabs — the selected clip's own controls vs. everything that
  // applies to the whole document — means switching context no longer
  // requires scrolling past unrelated collapsed sections.
  const [tab, setTab] = useState<'clip' | 'document'>('clip');

  const hasClip = selected?.type === 'clip' || selected?.type === 'sticker';

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden p-3">
      <div role="tablist" aria-label={t('propertiesTabsLabel')} className="mb-2 flex shrink-0 gap-2 border-b border-border">
        {(['clip', 'document'] as const).map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={
              tab === id
                ? 'border-b-2 border-primary px-1 pb-2 text-sm font-medium text-primary'
                : 'border-b-2 border-transparent px-1 pb-2 text-sm text-muted hover:text-text'
            }
          >
            {id === 'clip' ? t('propertiesTabClip') : t('propertiesTabDocument')}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === 'clip' ? (
          hasClip && selected ? (
            <div className="flex flex-col gap-4">
              <ClipAdjustControls
                key={`${selected.id}-${syncNonce}`}
                elementId={selected.id}
                initialVolume={selected.volume_millipercent}
                initialSpeed={selected.speed_millipercent}
                disabled={disabled}
                onCommit={onApply}
              />
              <EffectsMaskControls
                key={`${selected.id}-effects-${syncNonce}`}
                elementId={selected.id}
                initialEffects={selected.effects}
                initialMask={selected.mask}
                disabled={disabled}
                onCommit={onApply}
              />
              <KeyframeControls
                key={`${selected.id}-keyframes-${syncNonce}`}
                elementId={selected.id}
                initialAnimations={selected.animations}
                baseVolumeMillipercent={selected.volume_millipercent}
                disabled={disabled}
                onCommit={onApply}
              />
              <TransitionControls
                key={`${selected.id}-transitions-${syncNonce}`}
                elementId={selected.id}
                durationTicks={selected.duration_ticks}
                initialTransitionIn={selected.transition_in}
                initialTransitionOut={selected.transition_out}
                disabled={disabled}
                onCommit={onApply}
              />
            </div>
          ) : (
            <p className="text-xs text-muted">{t('propertiesEmptyHint')}</p>
          )
        ) : (
          <div className="flex flex-col gap-2">
            <CollapsibleSection label={t('exportTitle')} defaultOpen>
              <ExportPanel
                revisionId={revisionId}
                document={document}
                assets={assets}
                durationTicks={durationTicks}
                draftId={draftId}
                disabled={disabled}
                profiles={profiles}
                defaultProfile={defaultProfile}
              />
            </CollapsibleSection>
            <CollapsibleSection label={t('historyPanelTitle')}>
              <HistoryPanel
                cutId={cutId}
                headRevisionId={revisionId}
                disabled={disabled}
                onRestore={onRestore}
              />
            </CollapsibleSection>
            <CollapsibleSection label={t('canvasPanelTitle')}>
              <CanvasPanel document={document} disabled={disabled} onApply={onApply} />
            </CollapsibleSection>
            <CollapsibleSection label={t('captionBatchTitle')}>
              <CaptionBatchPanel
                key={syncNonce}
                document={document}
                disabled={disabled}
                onApply={onApply}
              />
            </CollapsibleSection>
            <CollapsibleSection label={t('planTitle')}>
              <EditPlanPanel
                cutId={cutId}
                leaseId={leaseId}
                leaseToken={leaseToken}
                disabled={disabled}
                onApplied={onPlanApplied}
              />
            </CollapsibleSection>
          </div>
        )}
      </div>
    </div>
  );
}
