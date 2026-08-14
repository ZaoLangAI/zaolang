'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  delayUntilSignedUrlRefresh,
  isImageMediaUrl,
  isNotAllowedError,
  isVideoMediaUrl,
  mediaObjectKey,
  pauseMedia,
  playMedia,
  readMediaDuration,
} from '@/components/media/safe-media-playback';
import { useAvailableStage } from '@/components/media/use-available-stage';
import { seekVideoToFirstFrame, VideoFirstFrame } from '@/components/media/video-first-frame';
import { Button } from '@/components/ui/button';
import {
  IconFullscreen,
  IconGear,
  IconPause,
  IconPlay,
  IconVolume,
  IconVolumeOff,
} from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import {
  fitWithinReferenceCanvas,
  parseCssRatio,
  referenceStageFallbackStyle,
} from '@/lib/devices';
import { formatDuration } from '@/lib/format';

/**
 * Video player with the control set the design calls for.
 *
 * Custom rather than native controls because the poster, scrim and control bar
 * all have to sit in the themed surface — but every control is a real button
 * with a label, and the whole bar is keyboard reachable.
 *
 * The default stage follows the file's ratio: landscape fills the parent
 * column, portrait stays phone-sized. Pass `aspectRatio={null}` when the
 * parent already has a fixed size (device frame, hero fill).
 */
const DEFAULT_RATIO = 16 / 9;
const HAVE_METADATA = 1;

export function VideoPlayer({
  src,
  poster,
  title,
  className,
  lazyMedia = false,
  aspectRatio,
  objectFit = 'contain',
  bare = false,
  refreshSrc,
}: {
  src?: string | null;
  poster?: string | null;
  title: string;
  className?: string;
  /** When true, keep the poster until the user presses play (discover hero). */
  lazyMedia?: boolean;
  /**
   * CSS `aspect-ratio` for the media box.
   *
   * Left out, the box adopts the file's own ratio: landscape follows the
   * parent width, portrait stays phone-sized. Pass `null` when the parent
   * already has a fixed size.
   */
  aspectRatio?: string | null;
  /** `cover` fills a frame whose ratio is not the file's, e.g. a phone screen. */
  objectFit?: 'contain' | 'cover';
  /** Drops the rounded border; the device frame supplies its own screen edge. */
  bare?: boolean;
  /** Mint a fresh signed URL when the current one is about to expire or 403s. */
  refreshSrc?: () => Promise<string | null>;
}) {
  const t = useTranslations('a11y');
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const playInFlightRef = useRef<Promise<void> | null>(null);
  const refreshSrcRef = useRef(refreshSrc);
  const startPlayRef = useRef<(options: { userGesture: boolean }) => Promise<void>>(
    async () => undefined,
  );
  const requestFreshSrcRef = useRef<() => Promise<string | null>>(async () => null);
  const refreshingRef = useRef(false);
  const restoreRef = useRef<{ time: number; playing: boolean } | null>(null);

  const fillParent = aspectRatio === null;
  const avail = useAvailableStage(measureRef);

  const [activeSrc, setActiveSrc] = useState<string | null>(() =>
    lazyMedia ? null : (src ?? null),
  );
  const [srcGate, setSrcGate] = useState({ src, lazyMedia });
  if (src !== srcGate.src || lazyMedia !== srcGate.lazyMedia) {
    setSrcGate({ src, lazyMedia });
    if (!src) {
      if (!lazyMedia) setActiveSrc(null);
    } else {
      setActiveSrc((currentSrc) => {
        if (currentSrc == null) return lazyMedia ? currentSrc : src;
        if (currentSrc === src) return currentSrc;
        return src;
      });
    }
  }
  const [pendingPlay, setPendingPlay] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [intrinsicRatio, setIntrinsicRatio] = useState<number | null>(null);
  const [timelineSrc, setTimelineSrc] = useState(activeSrc);
  if (activeSrc !== timelineSrc) {
    setTimelineSrc(activeSrc);
    setDuration(0);
    setCurrent(0);
    setIntrinsicRatio(null);
  }
  const [playbackError, setPlaybackError] = useState(false);
  const [needsUnmute, setNeedsUnmute] = useState(false);

  const ratio = parseCssRatio(aspectRatio) ?? intrinsicRatio ?? DEFAULT_RATIO;
  const stage = fitWithinReferenceCanvas({
    ratio,
    availWidth: avail.width,
    availHeight: avail.height,
  });
  const canSeek = duration > 0;

  const startPlay = useCallback(async (options: { userGesture: boolean }) => {
    const video = videoRef.current;
    if (!video) return;
    setPlaybackError(false);
    if (options.userGesture) {
      video.muted = false;
      video.volume = 1;
      setNeedsUnmute(false);
    }
    const run = (async () => {
      try {
        await playMedia(video);
      } catch (error) {
        if (isNotAllowedError(error)) {
          video.muted = true;
          setNeedsUnmute(true);
          await playMedia(video);
          return;
        }
        throw error;
      }
    })();
    playInFlightRef.current = run;
    try {
      await run;
    } catch {
      setPlaybackError(true);
    } finally {
      if (playInFlightRef.current === run) playInFlightRef.current = null;
    }
  }, []);

  const startPause = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    const inflight = playInFlightRef.current;
    const run = pauseMedia(video, inflight);
    playInFlightRef.current = run;
    try {
      await run;
    } finally {
      if (playInFlightRef.current === run) playInFlightRef.current = null;
    }
  }, []);

  const applyFreshSrc = useCallback((next: string) => {
    const video = videoRef.current;
    const currentSrc = video?.currentSrc || video?.src || null;
    if (video && currentSrc && mediaObjectKey(currentSrc) === mediaObjectKey(next)) {
      restoreRef.current = { time: video.currentTime, playing: !video.paused };
    }
    setPlaybackError(false);
    setActiveSrc(next);
  }, []);

  const requestFreshSrc = useCallback(async (): Promise<string | null> => {
    const refresh = refreshSrcRef.current;
    if (!refresh || refreshingRef.current) return null;
    refreshingRef.current = true;
    try {
      const next = await refresh();
      if (next) applyFreshSrc(next);
      return next;
    } catch {
      return null;
    } finally {
      refreshingRef.current = false;
    }
  }, [applyFreshSrc]);

  useEffect(() => {
    refreshSrcRef.current = refreshSrc;
  }, [refreshSrc]);
  useEffect(() => {
    startPlayRef.current = startPlay;
  }, [startPlay]);
  useEffect(() => {
    requestFreshSrcRef.current = requestFreshSrc;
  }, [requestFreshSrc]);

  const togglePlay = useCallback(() => {
    if (lazyMedia && !activeSrc && src) {
      setActiveSrc(src);
      setPendingPlay(true);
      return;
    }
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void startPlay({ userGesture: true });
    else void startPause();
  }, [activeSrc, lazyMedia, src, startPause, startPlay]);

  const seekTo = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video || !Number.isFinite(seconds)) return;
    video.currentTime = seconds;
    setCurrent(seconds);
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !activeSrc) return;

    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => setPlaying(false);
    const onTime = () => setCurrent(video.currentTime);
    const syncTimeline = () => {
      setDuration(readMediaDuration(video));
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        setIntrinsicRatio(video.videoWidth / video.videoHeight);
      }
    };
    const onMeta = () => {
      syncTimeline();
      const restore = restoreRef.current;
      if (restore) {
        restoreRef.current = null;
        if (restore.time > 0) video.currentTime = restore.time;
        if (restore.playing) void startPlayRef.current({ userGesture: false });
        return;
      }
      seekVideoToFirstFrame(video);
    };
    const onVolume = () => setMuted(video.muted);
    const onError = () => {
      void (async () => {
        const before = video.getAttribute('src');
        const next = await requestFreshSrcRef.current();
        if (!next || next === before) setPlaybackError(true);
      })();
    };

    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('ended', onEnded);
    video.addEventListener('timeupdate', onTime);
    video.addEventListener('loadedmetadata', onMeta);
    video.addEventListener('durationchange', syncTimeline);
    video.addEventListener('loadeddata', syncTimeline);
    video.addEventListener('volumechange', onVolume);
    video.addEventListener('error', onError);
    const missedMeta = window.setTimeout(() => {
      if (video.readyState >= HAVE_METADATA) onMeta();
    }, 0);
    return () => {
      window.clearTimeout(missedMeta);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('ended', onEnded);
      video.removeEventListener('timeupdate', onTime);
      video.removeEventListener('loadedmetadata', onMeta);
      video.removeEventListener('durationchange', syncTimeline);
      video.removeEventListener('loadeddata', syncTimeline);
      video.removeEventListener('volumechange', onVolume);
      video.removeEventListener('error', onError);
      void pauseMedia(video, playInFlightRef.current);
    };
  }, [activeSrc]);

  useEffect(() => {
    if (!pendingPlay || !activeSrc) return;
    const play = window.setTimeout(() => {
      void startPlay({ userGesture: false }).finally(() => setPendingPlay(false));
    }, 0);
    return () => window.clearTimeout(play);
  }, [pendingPlay, activeSrc, startPlay]);

  useEffect(() => {
    if (!activeSrc || !refreshSrcRef.current) return;
    const delay = delayUntilSignedUrlRefresh(activeSrc);
    if (delay == null) return;
    const timer = window.setTimeout(() => {
      void requestFreshSrc();
    }, delay);
    return () => window.clearTimeout(timer);
  }, [activeSrc, requestFreshSrc]);

  const retryPlayback = () => {
    void (async () => {
      if (refreshSrcRef.current) {
        const next = await requestFreshSrc();
        if (!next && playbackError) return;
      }
      await startPlay({ userGesture: true });
    })();
  };

  const unmuteToHear = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = false;
    video.volume = 1;
    setNeedsUnmute(false);
    if (video.paused) void startPlay({ userGesture: true });
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    // Space and arrows are what people already expect from a video surface.
    if (event.key === ' ' || event.key === 'k') {
      event.preventDefault();
      togglePlay();
    } else if (event.key === 'ArrowRight' && videoRef.current && canSeek) {
      seekTo(Math.min(duration, videoRef.current.currentTime + 5));
    } else if (event.key === 'ArrowLeft' && videoRef.current) {
      seekTo(Math.max(0, videoRef.current.currentTime - 5));
    } else if (event.key === 'm' && videoRef.current) {
      videoRef.current.muted = !videoRef.current.muted;
    }
  };

  const measured = avail.width > 0;
  const stageStyle = fillParent
    ? undefined
    : measured
      ? { width: stage.width, height: stage.height }
      : referenceStageFallbackStyle(ratio);
  const stillPoster = poster && isImageMediaUrl(poster) ? poster : null;
  const idleFirstFrameSrc =
    !activeSrc && src && (isVideoMediaUrl(poster) || !stillPoster) ? src : null;

  return (
    <div ref={measureRef} className={cn('w-full', fillParent ? 'h-full' : 'flex justify-center')}>
      <div
        ref={containerRef}
        className={cn(
          'relative overflow-hidden bg-black',
          fillParent && 'size-full',
          !bare && 'rounded-[var(--radius-md)] border border-border',
          className,
        )}
        style={stageStyle}
        onKeyDown={onKeyDown}
      >
        <div className="size-full">
          {activeSrc ? (
            // Caption tracks arrive with the asset pack; until then there is
            // nothing to attach to a <track>.
            <video
              ref={videoRef}
              src={activeSrc}
              poster={stillPoster ?? undefined}
              playsInline
              preload={lazyMedia ? 'none' : 'metadata'}
              aria-label={title}
              className={cn('size-full', objectFit === 'cover' ? 'object-cover' : 'object-contain')}
              onClick={togglePlay}
            />
          ) : stillPoster ? (
            // eslint-disable-next-line @next/next/no-img-element -- object URLs from storage are already sized; Image would re-proxy them.
            <img
              src={stillPoster}
              alt={title}
              className="size-full cursor-pointer object-cover"
              onClick={togglePlay}
            />
          ) : idleFirstFrameSrc ? (
            <VideoFirstFrame
              src={idleFirstFrameSrc}
              label={title}
              className="cursor-pointer"
              onClick={togglePlay}
            />
          ) : (
            <div className="grid size-full place-items-center text-sm text-muted">{title}</div>
          )}
        </div>

        {playbackError ? (
          <div className="absolute inset-0 z-10 grid place-items-center bg-black/65 px-4">
            <div className="flex flex-col items-center gap-3 text-center">
              <p className="text-sm text-white">{t('playbackError')}</p>
              <Button size="sm" variant="secondary" onClick={retryPlayback}>
                {t('retryPlayback')}
              </Button>
            </div>
          </div>
        ) : null}

        {needsUnmute && !playbackError ? (
          <button
            type="button"
            onClick={unmuteToHear}
            className="absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-full bg-black/70 px-3 py-2 text-xs text-white hover:bg-black/85"
          >
            {t('unmuteToHear')}
          </button>
        ) : null}

        <div className="absolute inset-x-0 bottom-0 flex items-center gap-2 bg-gradient-to-t from-black/85 to-transparent px-3 pb-3 pt-10 xs:gap-3 xs:px-4">
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
            max={canSeek ? duration : 1}
            step={0.1}
            value={canSeek ? Math.min(current, duration) : 0}
            disabled={!canSeek}
            aria-label={t('seek')}
            onChange={(event) => seekTo(Number(event.target.value))}
            className="h-1 w-full min-w-0 appearance-none rounded-full bg-white/25 accent-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-50"
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
    </div>
  );
}
