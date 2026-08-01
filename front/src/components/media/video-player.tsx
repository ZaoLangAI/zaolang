'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  IconFullscreen,
  IconGear,
  IconPause,
  IconPlay,
  IconVolume,
  IconVolumeOff,
} from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { formatDuration } from '@/lib/format';

/**
 * Video player with the control set the design calls for.
 *
 * Custom rather than native controls because the poster, scrim and control bar
 * all have to sit in the themed surface — but every control is a real button
 * with a label, and the whole bar is keyboard reachable.
 */
export function VideoPlayer({
  src,
  poster,
  title,
  className,
}: {
  src?: string | null;
  poster?: string | null;
  title: string;
  className?: string;
}) {
  const t = useTranslations('a11y');
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onTime = () => setCurrent(video.currentTime);
    const onMeta = () => setDuration(video.duration || 0);
    const onVolume = () => setMuted(video.muted);

    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('timeupdate', onTime);
    video.addEventListener('loadedmetadata', onMeta);
    video.addEventListener('volumechange', onVolume);
    return () => {
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('timeupdate', onTime);
      video.removeEventListener('loadedmetadata', onMeta);
      video.removeEventListener('volumechange', onVolume);
    };
  }, [src]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    // Space and arrows are what people already expect from a video surface.
    if (event.key === ' ' || event.key === 'k') {
      event.preventDefault();
      togglePlay();
    } else if (event.key === 'ArrowRight' && videoRef.current) {
      videoRef.current.currentTime = Math.min(duration, videoRef.current.currentTime + 5);
    } else if (event.key === 'ArrowLeft' && videoRef.current) {
      videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - 5);
    } else if (event.key === 'm' && videoRef.current) {
      videoRef.current.muted = !videoRef.current.muted;
    }
  };

  return (
    <div
      ref={containerRef}
      className={cn(
        'relative overflow-hidden rounded-[var(--radius-md)] border border-border bg-black',
        className,
      )}
      onKeyDown={onKeyDown}
    >
      <div className="aspect-video w-full">
        {src ? (
          // Caption tracks arrive with the asset pack; until then there is
          // nothing to attach to a <track>.
          <video
            ref={videoRef}
            src={src}
            poster={poster ?? undefined}
            playsInline
            preload="metadata"
            aria-label={title}
            className="size-full object-contain"
            onClick={togglePlay}
          />
        ) : poster ? (
          // eslint-disable-next-line @next/next/no-img-element -- object URLs from storage are already sized; Image would re-proxy them.
          <img src={poster} alt={title} className="size-full object-cover" />
        ) : (
          <div className="grid size-full place-items-center text-sm text-muted">{title}</div>
        )}
      </div>

      <div className="absolute inset-x-0 bottom-0 flex items-center gap-3 bg-gradient-to-t from-black/85 to-transparent px-4 pb-3 pt-10">
        <button
          type="button"
          onClick={togglePlay}
          aria-label={playing ? t('pause') : t('play')}
          className="grid size-10 shrink-0 place-items-center rounded-full bg-white/95 text-black"
        >
          {playing ? <IconPause className="size-4" /> : <IconPlay className="size-4" />}
        </button>

        <span className="tabular shrink-0 text-xs text-white/85">
          {formatDuration(current)} / {formatDuration(duration)}
        </span>

        <input
          type="range"
          min={0}
          max={Math.max(duration, 0.1)}
          step={0.1}
          value={current}
          aria-label={t('seek')}
          onChange={(event) => {
            const video = videoRef.current;
            if (video) video.currentTime = Number(event.target.value);
          }}
          className="h-1 w-full appearance-none rounded-full bg-white/25 accent-[var(--primary)]"
        />

        <button
          type="button"
          onClick={() => {
            const video = videoRef.current;
            if (video) video.muted = !video.muted;
          }}
          aria-label={muted ? t('unmute') : t('mute')}
          className="shrink-0 text-white/85 hover:text-white"
        >
          {muted ? <IconVolumeOff className="size-5" /> : <IconVolume className="size-5" />}
        </button>

        <button
          type="button"
          aria-label={t('settings')}
          className="hidden shrink-0 text-white/85 hover:text-white sm:block"
        >
          <IconGear className="size-5" />
        </button>

        <button
          type="button"
          onClick={() => void containerRef.current?.requestFullscreen?.()}
          aria-label={t('fullscreen')}
          className="shrink-0 text-white/85 hover:text-white"
        >
          <IconFullscreen className="size-5" />
        </button>
      </div>
    </div>
  );
}
