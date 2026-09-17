'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import type { EditCommand } from './engine/ports';

/**
 * Local drag state seeded from the selected element. The parent keys this
 * by element id *and* a sync generation counter that bumps on every
 * successful command/restore/reload, so both switching selection and any
 * server round-trip remount (and re-seed) it — otherwise a commit that
 * silently failed (e.g. a revision conflict) would leave this control
 * showing the edit it tried to make forever, even after the rest of the
 * app already recovered. Commits to the server on release instead of on
 * every drag tick.
 */
export function ClipAdjustControls({
  elementId,
  initialVolume,
  initialSpeed,
  disabled,
  onCommit,
}: {
  elementId: string;
  initialVolume: number;
  initialSpeed: number;
  disabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const [volume, setVolume] = useState(initialVolume);
  const [speed, setSpeed] = useState(initialSpeed);

  const commitVolume = () =>
    onCommit([{ type: 'set_clip_volume', element_id: elementId, volume_millipercent: volume }]);
  const commitSpeed = () =>
    onCommit([{ type: 'set_clip_speed', element_id: elementId, speed_millipercent: speed }]);

  return (
    <div className="flex flex-col gap-3 text-xs text-muted">
      <label className="flex flex-col gap-1">
        {t('volume')} {Math.round(volume / 1000)}%
        <input
          type="range"
          min={0}
          max={200_000}
          step={5_000}
          value={volume}
          disabled={disabled}
          onChange={(event) => setVolume(Number(event.target.value))}
          onPointerUp={commitVolume}
          onBlur={commitVolume}
          className="w-full accent-primary"
        />
      </label>
      <label className="flex flex-col gap-1">
        {t('speed')} {Math.round(speed / 1000)}%
        <input
          type="range"
          min={25_000}
          max={400_000}
          step={5_000}
          value={speed}
          disabled={disabled}
          onChange={(event) => setSpeed(Number(event.target.value))}
          onPointerUp={commitSpeed}
          onBlur={commitSpeed}
          className="w-full accent-primary"
        />
      </label>
    </div>
  );
}
