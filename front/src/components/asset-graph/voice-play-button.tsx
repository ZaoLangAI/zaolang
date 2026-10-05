'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { IconPlay } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

/** Plays / stops one audio URL (a voice's preview or sample). */
export function VoicePlayButton({
  url,
  label,
  className,
}: {
  url: string;
  label?: string;
  className?: string;
}) {
  const t = useTranslations('assetGraph');
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(
    () => () => {
      audio.current?.pause();
    },
    [],
  );

  const toggle = () => {
    if (!audio.current) {
      audio.current = new Audio(url);
      audio.current.addEventListener('ended', () => setPlaying(false));
      audio.current.addEventListener('pause', () => setPlaying(false));
    }
    if (playing) {
      audio.current.pause();
      audio.current.currentTime = 0;
      return;
    }
    void audio.current.play().then(
      () => setPlaying(true),
      () => setPlaying(false),
    );
  };

  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        toggle();
      }}
      aria-pressed={playing}
      className={cn(
        'nodrag inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] text-text hover:border-border-strong focus-visible:outline-2',
        playing && 'border-primary text-primary',
        className,
      )}
    >
      <IconPlay className="size-3" />
      {playing ? t('stop') : (label ?? t('play'))}
    </button>
  );
}
