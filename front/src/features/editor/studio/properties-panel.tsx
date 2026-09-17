'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { CollapsibleSection } from '@/components/studio/collapsible-section';
import { Button } from '@/components/ui/button';
import { IconCopy, IconTrash } from '@/components/ui/icons';
import type { ShortformProfile } from '@/lib/api/types';
import { cn } from '@/lib/cn';

import type { EditorActions } from '../actions';
import { CanvasPanel } from '../canvas-panel';
import { CaptionBatchPanel } from '../caption-batch-panel';
import { ClipAdjustControls } from '../clip-adjust-controls';
import { EditPlanPanel } from '../edit-plan-panel';
import { resolveNumberAtTime } from '../engine/animation';
import type { CanonicalDocument, EditCommand, ResolvedAsset, TimelineElement } from '../engine/ports';
import { TICKS_PER_SECOND } from '../engine/ports';
import { EffectsMaskControls } from '../effects-mask-controls';
import { ExportPanel } from '../export-panel';
import { HistoryPanel } from '../history-panel';
import { KeyframeControls } from '../keyframe-controls';
import { useEditorUi } from '../store';
import { canvasFps, formatTimecode } from '../timeline/geometry';
import { keyframeTickFor, resolveTransform, transformCommands } from '../transform-gizmo';
import { TransitionControls } from '../transition-controls';
import { NumberField } from './number-field';

export type PropertiesTab = 'element' | 'document';

type ElementSection = 'transform' | 'audio' | 'effects' | 'keyframes' | 'transitions';

/**
 * Adapted from OpenCut's `components/editor/panels/properties/index.tsx` and
 * its per-type registry (`registry.ts`): the selection decides which set of
 * sub-tabs shows — clip (transform / audio / effects / keyframes /
 * transitions), sticker (same minus audio), caption (text + timing), or a
 * multi-selection summary. The "document" tab keeps the whole-cut panels
 * (export / history / canvas / AI plan) reachable without scrolling past a
 * selected element's controls.
 */
export function PropertiesPanel({
  document,
  assets,
  durationTicks,
  revisionId,
  syncNonce,
  draftId,
  disabled,
  serverBusy,
  profiles,
  defaultProfile,
  selected,
  selectedIds,
  actions,
  cutId,
  leaseId,
  leaseToken,
  onApply,
  onPlanApplied,
  onRestore,
  tab,
  onTabChange,
  exportRequestNonce,
}: {
  document: CanonicalDocument;
  assets: ResolvedAsset[];
  durationTicks: number;
  revisionId: string | null;
  syncNonce: number;
  draftId: string | null;
  disabled: boolean;
  /** Export/history/restore need a settled server head; local edits do not. */
  serverBusy: boolean;
  profiles: ShortformProfile[];
  defaultProfile: string | null;
  selected: TimelineElement | undefined;
  selectedIds: string[];
  actions: EditorActions;
  cutId: string;
  leaseId: string | null;
  leaseToken: string | null;
  onApply: (commands: EditCommand[]) => void;
  onPlanApplied: () => void;
  onRestore: (revisionId: string) => void;
  tab: PropertiesTab;
  onTabChange: (tab: PropertiesTab) => void;
  /** Bumped by the header's export button — remounts the export section open. */
  exportRequestNonce: number;
}) {
  const t = useTranslations('editor');
  const multi = selectedIds.length > 1;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden p-3">
      <div role="tablist" aria-label={t('propertiesTabsLabel')} className="mb-2 flex shrink-0 gap-2 border-b border-border">
        {(['element', 'document'] as const).map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => onTabChange(id)}
            className={
              tab === id
                ? 'border-b-2 border-primary px-1 pb-2 text-sm font-medium text-primary'
                : 'border-b-2 border-transparent px-1 pb-2 text-sm text-muted hover:text-text'
            }
          >
            {id === 'element' ? t('propertiesTabClip') : t('propertiesTabDocument')}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === 'element' ? (
          multi ? (
            <MultiSelectionProperties count={selectedIds.length} disabled={disabled} actions={actions} />
          ) : selected?.type === 'caption' ? (
            <CaptionProperties
              key={`${selected.id}-${syncNonce}`}
              element={selected}
              fps={canvasFps(document.canvas)}
              disabled={disabled}
              onApply={onApply}
            />
          ) : selected ? (
            <ElementProperties
              element={selected}
              syncNonce={syncNonce}
              disabled={disabled}
              onApply={onApply}
            />
          ) : (
            <p className="text-xs text-muted">{t('propertiesEmptyHint')}</p>
          )
        ) : (
          <div className="flex flex-col gap-2">
            <CollapsibleSection key={`export-${exportRequestNonce}`} label={t('exportTitle')} defaultOpen>
              <ExportPanel
                revisionId={revisionId}
                document={document}
                assets={assets}
                durationTicks={durationTicks}
                draftId={draftId}
                disabled={disabled || serverBusy}
                profiles={profiles}
                defaultProfile={defaultProfile}
              />
            </CollapsibleSection>
            <CollapsibleSection label={t('historyPanelTitle')}>
              <HistoryPanel
                cutId={cutId}
                headRevisionId={revisionId}
                disabled={disabled || serverBusy}
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
                disabled={disabled || serverBusy}
                onApplied={onPlanApplied}
              />
            </CollapsibleSection>
          </div>
        )}
      </div>
    </div>
  );
}

function SubTabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: T; label: string }[];
  active: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="mb-3 flex flex-wrap gap-1">
      {tabs.map((item) => (
        <button
          key={item.id}
          role="tab"
          type="button"
          aria-selected={active === item.id}
          onClick={() => onChange(item.id)}
          className={cn(
            'rounded-full px-2.5 py-1 text-[11px] transition-colors',
            active === item.id ? 'bg-primary/15 text-primary' : 'text-muted hover:bg-surface-soft hover:text-text',
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function ElementProperties({
  element,
  syncNonce,
  disabled,
  onApply,
}: {
  element: TimelineElement;
  syncNonce: number;
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const isSticker = element.type === 'sticker';
  const tabs: { id: ElementSection; label: string }[] = [
    { id: 'transform', label: t('propsTabTransform') },
    ...(isSticker ? [] : [{ id: 'audio' as const, label: t('propsTabAudio') }]),
    { id: 'effects', label: t('propsTabEffects') },
    { id: 'keyframes', label: t('propsTabKeyframes') },
    { id: 'transitions', label: t('propsTabTransitions') },
  ];
  const [section, setSection] = useState<ElementSection>('transform');
  const active = tabs.some((item) => item.id === section) ? section : 'transform';

  return (
    <div className="flex flex-col">
      <SubTabs tabs={tabs} active={active} onChange={setSection} />
      {active === 'transform' ? (
        <TransformProperties element={element} disabled={disabled} onApply={onApply} />
      ) : active === 'audio' ? (
        <ClipAdjustControls
          key={`${element.id}-${syncNonce}`}
          elementId={element.id}
          initialVolume={element.volume_millipercent}
          initialSpeed={element.speed_millipercent}
          disabled={disabled}
          onCommit={onApply}
        />
      ) : active === 'effects' ? (
        <EffectsMaskControls
          key={`${element.id}-effects-${syncNonce}`}
          elementId={element.id}
          initialEffects={element.effects}
          initialMask={element.mask}
          disabled={disabled}
          onCommit={onApply}
        />
      ) : active === 'keyframes' ? (
        <KeyframeControls
          key={`${element.id}-keyframes-${syncNonce}`}
          elementId={element.id}
          initialAnimations={element.animations}
          baseVolumeMillipercent={element.volume_millipercent}
          disabled={disabled}
          onCommit={onApply}
        />
      ) : (
        <TransitionControls
          key={`${element.id}-transitions-${syncNonce}`}
          elementId={element.id}
          durationTicks={element.duration_ticks}
          initialTransitionIn={element.transition_in}
          initialTransitionOut={element.transition_out}
          disabled={disabled}
          onCommit={onApply}
        />
      )}
    </div>
  );
}

/**
 * Numeric twins of the on-canvas gizmo — same resolution at the playhead,
 * same `set_keyframe` write rule (`keyframeTickFor`), so the two never
 * disagree about what "the element's position" means.
 */
function TransformProperties({
  element,
  disabled,
  onApply,
}: {
  element: TimelineElement;
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const transform = resolveTransform(element, playheadTicks);
  const opacityMilli = resolveNumberAtTime(element.animations, 'opacity', playheadTicks, 100_000);

  const commitTransform = (patch: Partial<typeof transform>) => {
    const commands = transformCommands(element, transform, { ...transform, ...patch }, playheadTicks);
    if (commands.length) onApply(commands);
  };

  return (
    <div className="flex flex-col gap-2">
      <NumberField
        label={t('propX')}
        value={transform.xMilli / 10}
        defaultValue={0}
        min={-200}
        max={200}
        step={0.5}
        precision={1}
        unit="%"
        disabled={disabled}
        onCommit={(value) => commitTransform({ xMilli: value * 10 })}
      />
      <NumberField
        label={t('propY')}
        value={transform.yMilli / 10}
        defaultValue={0}
        min={-200}
        max={200}
        step={0.5}
        precision={1}
        unit="%"
        disabled={disabled}
        onCommit={(value) => commitTransform({ yMilli: value * 10 })}
      />
      <NumberField
        label={t('propScale')}
        value={transform.scaleMillipercent / 1000}
        defaultValue={100}
        min={10}
        max={500}
        step={0.5}
        precision={1}
        unit="%"
        disabled={disabled}
        onCommit={(value) => commitTransform({ scaleMillipercent: value * 1000 })}
      />
      <NumberField
        label={t('propRotation')}
        value={transform.rotationMillidegrees / 1000}
        defaultValue={0}
        min={-180}
        max={180}
        step={0.5}
        precision={1}
        unit="°"
        disabled={disabled}
        onCommit={(value) => commitTransform({ rotationMillidegrees: value * 1000 })}
      />
      <NumberField
        label={t('propOpacity')}
        value={opacityMilli / 1000}
        defaultValue={100}
        min={0}
        max={100}
        step={0.5}
        precision={0}
        unit="%"
        disabled={disabled}
        onCommit={(value) =>
          onApply([
            {
              type: 'set_keyframe',
              element_id: element.id,
              property: 'opacity',
              at_ticks: keyframeTickFor(element, 'opacity', playheadTicks),
              value: Math.round(value * 1000),
            },
          ])
        }
      />
      <p className="mt-1 text-[11px] text-muted">{t('transformKeyframeHint')}</p>
    </div>
  );
}

function CaptionProperties({
  element,
  fps,
  disabled,
  onApply,
}: {
  element: TimelineElement;
  fps: number;
  disabled: boolean;
  onApply: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const [text, setText] = useState(element.text ?? '');
  const startSeconds = element.start_ticks / TICKS_PER_SECOND;
  const durationSeconds = element.duration_ticks / TICKS_PER_SECOND;

  const commitText = () => {
    const next = text.trim();
    if (!next || next === element.text) {
      setText(element.text ?? '');
      return;
    }
    onApply([{ type: 'update_caption', element_id: element.id, text: next }]);
  };

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-xs text-muted">
        {t('captionText')}
        <textarea
          value={text}
          rows={3}
          disabled={disabled}
          onChange={(event) => setText(event.target.value)}
          onBlur={commitText}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.blur();
            } else if (event.key === 'Escape') {
              setText(element.text ?? '');
              event.currentTarget.blur();
            }
          }}
          className="w-full resize-none rounded-[var(--radius-sm)] border border-border bg-surface px-2 py-1.5 text-sm text-text outline-none focus:border-primary disabled:opacity-60"
        />
      </label>
      <NumberField
        label={t('captionStart')}
        value={startSeconds}
        defaultValue={startSeconds}
        min={0}
        max={24 * 3600}
        step={0.05}
        precision={2}
        unit="s"
        disabled={disabled}
        onCommit={(value) =>
          onApply([
            { type: 'update_caption', element_id: element.id, at_ticks: Math.round(value * TICKS_PER_SECOND) },
          ])
        }
      />
      <NumberField
        label={t('captionDuration')}
        value={durationSeconds}
        defaultValue={durationSeconds}
        min={0.05}
        max={3600}
        step={0.05}
        precision={2}
        unit="s"
        disabled={disabled}
        onCommit={(value) =>
          onApply([
            {
              type: 'update_caption',
              element_id: element.id,
              duration_ticks: Math.max(1, Math.round(value * TICKS_PER_SECOND)),
            },
          ])
        }
      />
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px] text-muted">
        <dt>{t('captionLanguage')}</dt>
        <dd className="text-text">{element.caption_language ?? t('captionLanguageUnset')}</dd>
        <dt>{t('captionEnd')}</dt>
        <dd className="font-mono text-text">
          {formatTimecode(element.start_ticks + element.duration_ticks, fps)}
        </dd>
      </dl>
    </div>
  );
}

function MultiSelectionProperties({
  count,
  disabled,
  actions,
}: {
  count: number;
  disabled: boolean;
  actions: EditorActions;
}) {
  const t = useTranslations('editor');
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-text">{t('multiSelected', { count })}</p>
      <p className="text-xs text-muted">{t('multiSelectedHint')}</p>
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" disabled={disabled} onClick={actions.duplicateSelected}>
          <IconCopy className="size-4" />
          {t('toolbarDuplicate')}
        </Button>
        <Button size="sm" variant="danger" disabled={disabled} onClick={actions.deleteSelected}>
          <IconTrash className="size-4" />
          {t('deleteSelected')}
        </Button>
      </div>
    </div>
  );
}
