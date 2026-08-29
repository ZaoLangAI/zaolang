'use client';

import { useTranslations } from 'next-intl';

import { CollapsibleSection } from '@/components/studio/collapsible-section';
import type { ShortformProfile } from '@/lib/api/types';

import { CanvasPanel } from '../canvas-panel';
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
  draftId,
  disabled,
  profiles,
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
  draftId: string | null;
  disabled: boolean;
  profiles: ShortformProfile[];
  selected: TimelineElement | undefined;
  cutId: string;
  leaseId: string | null;
  leaseToken: string | null;
  onApply: (commands: EditCommand[]) => void;
  onPlanApplied: () => void;
  onRestore: (revisionId: string) => void;
}) {
  const t = useTranslations('editor');

  const hasClip = selected?.type === 'clip' || selected?.type === 'sticker';

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto p-3">
      <CollapsibleSection label={t('propertiesTitle')} defaultOpen>
        {hasClip && selected ? (
          <>
            <ClipAdjustControls
              key={selected.id}
              elementId={selected.id}
              initialVolume={selected.volume_millipercent}
              initialSpeed={selected.speed_millipercent}
              disabled={disabled}
              onCommit={onApply}
            />
            <EffectsMaskControls
              key={`${selected.id}-effects`}
              elementId={selected.id}
              initialEffects={selected.effects}
              initialMask={selected.mask}
              disabled={disabled}
              onCommit={onApply}
            />
            <KeyframeControls
              key={`${selected.id}-keyframes`}
              elementId={selected.id}
              initialAnimations={selected.animations}
              disabled={disabled}
              onCommit={onApply}
            />
            <TransitionControls
              key={`${selected.id}-transitions`}
              elementId={selected.id}
              durationTicks={selected.duration_ticks}
              initialTransitionIn={selected.transition_in}
              initialTransitionOut={selected.transition_out}
              disabled={disabled}
              onCommit={onApply}
            />
          </>
        ) : (
          <p className="text-xs text-muted">{t('propertiesEmptyHint')}</p>
        )}
      </CollapsibleSection>
      <CollapsibleSection label={t('exportTitle')}>
        <ExportPanel
          revisionId={revisionId}
          document={document}
          assets={assets}
          durationTicks={durationTicks}
          draftId={draftId}
          disabled={disabled}
          profiles={profiles}
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
  );
}
