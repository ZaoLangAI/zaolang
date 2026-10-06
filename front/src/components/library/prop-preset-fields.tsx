'use client';

import { useTranslations } from 'next-intl';

import { Select } from '@/components/ui/field';
import {
  keysOf,
  PROP_STATES,
  type PropPresets,
  type PropState,
  SCENE_PERIODS,
  type ScenePeriod,
} from '@/features/image-assets/vocabulary';

/** A prop variant's two preset axes — condition (`prop_state`) and period,
 * the only keys `asset_variants.service` accepts for a prop. */
export function PropPresetFields({
  presets,
  onChange,
}: {
  presets: PropPresets;
  onChange: (next: PropPresets) => void;
}) {
  const t = useTranslations('props');
  const tPresets = useTranslations('remixPage');
  return (
    <div className="grid grid-cols-2 gap-2">
      <Select
        label={t('stateLabel')}
        value={presets.prop_state ?? ''}
        onChange={(event) =>
          onChange({ ...presets, prop_state: (event.target.value || null) as PropState | null })
        }
        options={[
          { value: '', label: tPresets('presets.none') },
          ...keysOf(PROP_STATES).map((key) => ({
            value: key,
            label: t(PROP_STATES[key].labelKey),
          })),
        ]}
      />
      <Select
        label={tPresets('presets.axisPeriod')}
        value={presets.period ?? ''}
        onChange={(event) =>
          onChange({ ...presets, period: (event.target.value || null) as ScenePeriod | null })
        }
        options={[
          { value: '', label: tPresets('presets.none') },
          ...keysOf(SCENE_PERIODS).map((key) => ({
            value: key,
            label: tPresets(`presets.${SCENE_PERIODS[key].labelKey}`),
          })),
        ]}
      />
    </div>
  );
}

/** Only the prop keys of a variant's stored presets. */
export function propPresetsOf(presets: Record<string, unknown> | null | undefined): PropPresets {
  const value = (presets ?? {}) as PropPresets;
  return { prop_state: value.prop_state ?? null, period: value.period ?? null };
}
