'use client';

import { useTranslations } from 'next-intl';

import { Select } from '@/components/ui/field';
import {
  SCENE_LIGHTINGS,
  SCENE_PERIODS,
  SCENE_STATES,
  SCENE_WEATHERS,
  type ScenePresets,
} from '@/features/image-assets/vocabulary';

export const PRESET_AXES = [
  { axis: 'lighting', table: SCENE_LIGHTINGS },
  { axis: 'weather', table: SCENE_WEATHERS },
  { axis: 'state', table: SCENE_STATES },
  { axis: 'period', table: SCENE_PERIODS },
] as const;

/** A scene variant's four preset axes; each change saves at once. */
export function ScenePresetFields({
  presets,
  onChange,
}: {
  presets: ScenePresets;
  onChange: (next: ScenePresets) => void;
}) {
  const tPresets = useTranslations('remixPage');
  return (
    <div className="grid grid-cols-2 gap-2">
      {PRESET_AXES.map(({ axis, table }) => (
        <Select
          key={axis}
          label={tPresets(`presets.axis${axis[0]?.toUpperCase()}${axis.slice(1)}`)}
          value={presets[axis] ?? ''}
          onChange={(event) => onChange({ ...presets, [axis]: event.target.value || null })}
          options={[
            { value: '', label: tPresets('presets.none') },
            ...Object.entries(table).map(([key, entry]) => ({
              value: key,
              label: tPresets(`presets.${entry.labelKey}`),
            })),
          ]}
        />
      ))}
    </div>
  );
}
