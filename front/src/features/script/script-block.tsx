'use client';

import { useTranslations } from 'next-intl';

import { IconVideo } from '@/components/ui/icons';
import { Link } from '@/i18n/navigation';
import { cn } from '@/lib/cn';

import type { ScriptBlock, ScriptBlockType } from './api';
import { EditableInlineText } from './editable-text';

/**
 * Full literal class strings (not template-built), matching
 * `components/ui/primitives.tsx`'s `badgeTones` recipe — Tailwind's scanner
 * only picks up class names it can find as literal text in a source file, so
 * `` `bg-script-${type}` `` would silently produce no styles at all.
 */
const BLOCK_TONE_CLASSES: Record<ScriptBlockType, string> = {
  scene: 'border-script-scene/30 bg-script-scene/10 text-script-scene',
  action: 'border-script-action/30 bg-script-action/10 text-script-action',
  camera: 'border-script-camera/30 bg-script-camera/10 text-script-camera',
  dialogue: 'border-script-dialogue/30 bg-script-dialogue/10 text-script-dialogue',
  breakpoint: 'border-script-breakpoint/30 bg-script-breakpoint/10 text-script-breakpoint',
};

const SWATCH_CLASSES: Record<ScriptBlockType, string> = {
  scene: 'bg-script-scene',
  action: 'bg-script-action',
  camera: 'bg-script-camera',
  dialogue: 'bg-script-dialogue',
  breakpoint: 'bg-script-breakpoint',
};

const BLOCK_TYPES: ScriptBlockType[] = ['scene', 'action', 'camera', 'dialogue', 'breakpoint'];

export function ScriptLegend({ className }: { className?: string }) {
  const t = useTranslations('scriptStudio');
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-xs text-muted',
        className,
      )}
    >
      {BLOCK_TYPES.map((type) => (
        <span key={type} className="flex items-center gap-1.5">
          <span className={cn('size-2.5 shrink-0 rounded-full', SWATCH_CLASSES[type])} />
          {t(`blockType.${type}`)}
        </span>
      ))}
    </div>
  );
}

export function ScriptBlockRow({
  block,
  onSave,
  breakpointVideoHref,
  viewGenerated,
}: {
  block: ScriptBlock;
  /** Present only while viewing the episode's true latest turn (see
   * `ScriptEditor`) — `episode.script_json` only ever holds the latest
   * turn's content, so hand-editing a browsed historical snapshot has
   * nowhere to persist. Omitted, the block renders as plain read-only
   * text, same as before this prop existed. */
  onSave?: (text: string) => void;
  /** Only set on a `breakpoint` block, and only when the segment it closes
   * resolves to at least one linked character/scene (see
   * `script-document-view.tsx`'s `resolveBreakpointRefs`) or already has a
   * generated clip — undefined renders the badge as plain (non-clickable)
   * text rather than a disabled link. */
  breakpointVideoHref?: string;
  /** The clip for this breakpoint already exists — badge reads "查看视频"
   * and `breakpointVideoHref` points at `/jobs/{id}` instead of generate. */
  viewGenerated?: boolean;
}) {
  const t = useTranslations('scriptStudio');

  // A breakpoint is a cut marker, not script content — it reads as a dashed
  // divider with the reasoning as a caption, never as another colored
  // paragraph the reader might mistake for something to shoot. The badge
  // itself doubles as the action: "查看视频" when a clip already exists,
  // otherwise "建议切分" into the video studio when the segment resolves
  // to at least one linked character/scene. Never a separate chip alongside.
  if (block.type === 'breakpoint') {
    const badgeClassName =
      'flex shrink-0 items-center gap-1.5 rounded-full border border-script-breakpoint/30 bg-script-breakpoint/10 px-2.5 py-1 text-[11px] font-medium';
    const badgeContent = (
      <>
        <IconVideo className="size-3" />
        {viewGenerated ? t('viewGeneratedVideo') : t('blockType.breakpoint')}
      </>
    );
    return (
      <div className="flex items-center gap-2 py-1 text-script-breakpoint">
        <span className="h-px flex-1 border-t border-dashed border-script-breakpoint/40" />
        {breakpointVideoHref ? (
          <Link href={breakpointVideoHref} className={cn(badgeClassName, 'hover:bg-script-breakpoint/20')}>
            {badgeContent}
          </Link>
        ) : (
          <span className={badgeClassName}>{badgeContent}</span>
        )}
        <span className="h-px flex-1 border-t border-dashed border-script-breakpoint/40" />
        {block.text ? (
          <span
            title={block.text}
            className="max-w-[40ch] shrink-0 truncate text-xs opacity-80"
          >
            {block.text}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'rounded-[var(--radius-sm)] border px-3 py-2 text-sm leading-relaxed',
        BLOCK_TONE_CLASSES[block.type],
      )}
    >
      <div className="mb-0.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide opacity-80">
        <span>{t(`blockType.${block.type}`)}</span>
        {block.type === 'dialogue' && block.character ? (
          <span className="normal-case opacity-100">· {block.character}</span>
        ) : null}
      </div>
      <EditableInlineText
        value={block.text}
        onCommit={(next) => onSave?.(next)}
        editable={!!onSave}
        className="block text-text"
        ariaLabel={t(`blockType.${block.type}`)}
        title={onSave ? t('editHint') : undefined}
      />
    </div>
  );
}
