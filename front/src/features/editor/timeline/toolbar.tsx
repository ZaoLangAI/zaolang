'use client';

import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';

import {
  IconAlignLeft,
  IconCopy,
  IconFlag,
  IconMagnet,
  IconMusic,
  IconRedo,
  IconScissors,
  IconTrash,
  IconUndo,
  IconVideo,
  IconZoomIn,
  IconZoomOut,
} from '@/components/ui/icons';

import type { EditorActions } from '../actions';
import type { Marker } from '../engine/ports';
import {
  ZOOM_BUTTON_FACTOR,
  clampZoom,
  formatTimecode,
  sliderFromZoom,
  zoomFromSlider,
} from './geometry';

function ToolButton({
  label,
  shortcut,
  onClick,
  disabled,
  active,
  children,
}: {
  label: string;
  shortcut?: string;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  children: ReactNode;
}) {
  const title = shortcut ? `${label} (${shortcut})` : label;
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex size-7 items-center justify-center rounded-[var(--radius-sm)] text-sm transition-colors disabled:opacity-40 ${
        active ? 'bg-primary/15 text-primary' : 'text-text hover:bg-surface-soft'
      }`}
    >
      {children}
    </button>
  );
}

function Divider() {
  return <span className="mx-1 h-4 w-px bg-border" aria-hidden />;
}

/**
 * Icon toolbar above the tracks, adapted from OpenCut's timeline toolbar:
 * edit verbs on the left (with their shortcuts in the tooltip), the marker
 * label editor in the middle when the playhead sits on one, and the
 * timecode + zoom controls on the right.
 */
export function TimelineToolbar({
  actions,
  disabled,
  hasSelection,
  snappingEnabled,
  zoom,
  onZoomChange,
  playheadTicks,
  durationTicks,
  fps,
  activeMarker,
  onMarkerLabelChange,
}: {
  actions: EditorActions;
  disabled: boolean;
  hasSelection: boolean;
  snappingEnabled: boolean;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  playheadTicks: number;
  durationTicks: number;
  fps: number;
  activeMarker: Marker | null;
  onMarkerLabelChange: (marker: Marker, label: string) => void;
}) {
  const t = useTranslations('editor');
  return (
    <div className="flex h-10 shrink-0 items-center gap-0.5 border-b border-border bg-surface px-2">
      <ToolButton
        label={t('undo')}
        shortcut="Ctrl+Z"
        onClick={actions.undo}
        disabled={disabled || !actions.canUndo}
      >
        <IconUndo />
      </ToolButton>
      <ToolButton
        label={t('redo')}
        shortcut="Ctrl+Shift+Z"
        onClick={actions.redo}
        disabled={disabled || !actions.canRedo}
      >
        <IconRedo />
      </ToolButton>
      <Divider />
      <ToolButton
        label={t('splitAtPlayhead')}
        shortcut="S"
        onClick={actions.splitAtPlayhead}
        disabled={disabled}
      >
        <IconScissors />
      </ToolButton>
      <ToolButton
        label={t('keepLeft')}
        shortcut="W"
        onClick={actions.keepLeft}
        disabled={disabled || !hasSelection}
      >
        <span className="text-[11px] font-semibold">◧</span>
      </ToolButton>
      <ToolButton
        label={t('keepRight')}
        shortcut="Q"
        onClick={actions.keepRight}
        disabled={disabled || !hasSelection}
      >
        <span className="text-[11px] font-semibold">◨</span>
      </ToolButton>
      <ToolButton
        label={t('duplicateSelected')}
        shortcut="Ctrl+D"
        onClick={actions.duplicateSelected}
        disabled={disabled || !hasSelection}
      >
        <IconCopy />
      </ToolButton>
      <ToolButton
        label={t('deleteSelected')}
        shortcut="Delete"
        onClick={actions.deleteSelected}
        disabled={disabled || !hasSelection}
      >
        <IconTrash />
      </ToolButton>
      <Divider />
      <ToolButton
        label={activeMarker ? t('markerDelete') : t('markerAdd')}
        shortcut="M"
        onClick={actions.toggleMarkerAtPlayhead}
        disabled={disabled}
        active={!!activeMarker}
      >
        <IconFlag />
      </ToolButton>
      {activeMarker ? (
        <input
          key={activeMarker.id}
          type="text"
          defaultValue={activeMarker.label ?? ''}
          placeholder={t('markerLabelPlaceholder')}
          disabled={disabled}
          maxLength={120}
          aria-label={t('markerLabelPlaceholder')}
          onBlur={(event) => {
            const next = event.target.value.trim();
            if (next !== (activeMarker.label ?? '')) onMarkerLabelChange(activeMarker, next);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') (event.target as HTMLInputElement).blur();
            event.stopPropagation();
          }}
          className="h-6 w-32 rounded-[var(--radius-sm)] border border-border bg-surface px-1.5 text-[11px] text-text"
        />
      ) : null}
      <ToolButton
        label={t('alignToPlayhead')}
        onClick={actions.alignSelectedToPlayhead}
        disabled={disabled || !hasSelection}
      >
        <IconAlignLeft />
      </ToolButton>
      <ToolButton
        label={snappingEnabled ? t('snappingOn') : t('snappingOff')}
        shortcut="N"
        onClick={actions.toggleSnapping}
        active={snappingEnabled}
      >
        <IconMagnet />
      </ToolButton>
      <Divider />
      <ToolButton
        label={t('addVideoTrack')}
        onClick={() => actions.addTrack('video')}
        disabled={disabled}
      >
        <IconVideo />
      </ToolButton>
      <ToolButton
        label={t('addAudioTrack')}
        onClick={() => actions.addTrack('audio')}
        disabled={disabled}
      >
        <IconMusic />
      </ToolButton>

      <span className="ml-auto font-mono text-[11px] tabular-nums text-muted">
        <span className="text-text">{formatTimecode(playheadTicks, fps)}</span>
        {' / '}
        {formatTimecode(durationTicks, fps)}
      </span>
      <Divider />
      <ToolButton
        label={t('timelineZoomOut')}
        onClick={() => onZoomChange(clampZoom(zoom / ZOOM_BUTTON_FACTOR))}
      >
        <IconZoomOut />
      </ToolButton>
      <input
        type="range"
        min={0}
        max={1}
        step={0.001}
        value={sliderFromZoom(zoom)}
        aria-label={t('timelineZoom')}
        onChange={(event) => onZoomChange(zoomFromSlider(Number(event.target.value)))}
        className="w-24 accent-primary"
      />
      <ToolButton
        label={t('timelineZoomIn')}
        onClick={() => onZoomChange(clampZoom(zoom * ZOOM_BUTTON_FACTOR))}
      >
        <IconZoomIn />
      </ToolButton>
    </div>
  );
}
