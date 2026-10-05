'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';
import { useTranslations } from 'next-intl';

import { Badge } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/cn';

import {
  LOOK_ROW,
  LOOK_ROWS_PAD,
  MAX_LOOK_ROWS,
  VOICE_FOOTER,
  VOICE_HEADER,
  type VoiceNode,
} from '../graph-model';
import { useAttributeLabel } from '../use-attribute-label';
import { VoicePlayButton } from '../voice-play-button';

/** A character voice as a class box: name and source, its attribute rows,
 * then its preview and the looks that speak with it. */
export function VoiceNodeCard({ data, selected }: NodeProps<VoiceNode>) {
  const t = useTranslations('assetGraph');
  const label = useAttributeLabel();
  const { voice, rows } = data;
  const shown = rows.slice(0, MAX_LOOK_ROWS);
  const summary =
    voice.source === 'clone'
      ? t('voiceCloneSummary')
      : [voice.model, voice.voice].filter(Boolean).join(' · ');
  return (
    <div
      style={{ width: data.width, height: data.height }}
      className={cn(
        'flex flex-col overflow-hidden rounded-[var(--radius-md)] border bg-surface shadow-sm transition-[border-color,box-shadow]',
        selected ? 'border-primary ring-2 ring-primary/40' : 'border-border',
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-3 !border-border !bg-surface"
      />
      <div
        style={{ height: VOICE_HEADER }}
        className="flex flex-col justify-center gap-0.5 border-b border-border px-3"
      >
        <p className="flex items-center gap-1.5 text-sm font-semibold">
          <span className="truncate">{voice.name}</span>
          {voice.is_default ? <Badge tone="primary">{t('defaultBadge')}</Badge> : null}
          <Badge>{voice.source === 'clone' ? t('voiceClone') : t('voicePreset')}</Badge>
        </p>
        <p className="truncate text-[11px] text-muted" title={summary}>
          {summary}
          {voice.params?.speed ? ` · ×${voice.params.speed}` : ''}
          {voice.params?.emotion ? ` · ${t(`emotion.${voice.params.emotion}`)}` : ''}
        </p>
      </div>
      {shown.length ? (
        <dl
          style={{ paddingTop: LOOK_ROWS_PAD / 2, paddingBottom: LOOK_ROWS_PAD / 2 }}
          className="border-b border-border px-3"
        >
          {shown.map((row, index) => {
            const text = label(row);
            return (
              <div
                key={index}
                style={{ height: LOOK_ROW }}
                className="flex items-center gap-2 text-[11px]"
              >
                <dt className="w-16 shrink-0 truncate text-muted">{text.label}</dt>
                <dd className="min-w-0 truncate">{text.value}</dd>
              </div>
            );
          })}
          {rows.length > MAX_LOOK_ROWS ? (
            <p style={{ height: LOOK_ROW }} className="flex items-center text-[11px] text-muted">
              {t('moreRows', { count: rows.length - MAX_LOOK_ROWS })}
            </p>
          ) : null}
        </dl>
      ) : null}
      <div style={{ height: VOICE_FOOTER }} className="mt-auto flex items-center gap-2 px-3">
        {data.previewPending ? (
          <span className="inline-flex items-center gap-1 text-[11px] text-primary">
            <Spinner className="size-3" /> {t('previewGenerating')}
          </span>
        ) : voice.preview?.url ? (
          <VoicePlayButton url={voice.preview.url} />
        ) : (
          <span className="text-[11px] text-muted">{t('noPreview')}</span>
        )}
        <span
          className="min-w-0 flex-1 truncate text-right text-[11px] text-muted"
          title={data.lookNames.join('、')}
        >
          {data.lookNames.length ? t('voiceLooks', { names: data.lookNames.join('、') }) : ''}
        </span>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!size-3 !border-border !bg-surface"
      />
    </div>
  );
}
