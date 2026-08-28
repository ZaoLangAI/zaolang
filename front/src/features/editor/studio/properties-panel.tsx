'use client';

import { useTranslations } from 'next-intl';

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
 * `ExportPanel` are document-level (not selection-scoped), so they render
 * as their own always-visible sections rather than inside the registry.
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

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-3">
      <ExportPanel
        revisionId={revisionId}
        document={document}
        assets={assets}
        durationTicks={durationTicks}
        draftId={draftId}
        disabled={disabled}
        profiles={profiles}
      />
      <HistoryPanel
        cutId={cutId}
        headRevisionId={revisionId}
        disabled={disabled}
        onRestore={onRestore}
      />
      <section className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold">{t('propertiesTitle')}</h2>
        {selected?.type === 'clip' || selected?.type === 'sticker' ? (
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
      </section>
      <CanvasPanel document={document} disabled={disabled} onApply={onApply} />
      <EditPlanPanel
        cutId={cutId}
        leaseId={leaseId}
        leaseToken={leaseToken}
        disabled={disabled}
        onApplied={onPlanApplied}
      />
    </div>
  );
}
