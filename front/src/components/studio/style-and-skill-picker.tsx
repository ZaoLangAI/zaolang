'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { StyleGalleryDialog } from '@/components/studio/style-gallery-dialog';
import { useAppliedSkills } from '@/components/studio/use-applied-skills';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/field';
import { IconClose, IconSparkle } from '@/components/ui/icons';
import { Poster } from '@/components/media/poster';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type {
  CreationSkillDetail,
  CreationSkillSummary,
  Operation,
  Page,
  StyleGalleryEntry,
  StylePreset,
} from '@/lib/api/types';
import { styleGalleryLabel } from '@/lib/style-gallery';
import { useResource } from '@/lib/use-resource';

export { KNOWN_PRESET_KEYS, MAX_APPLIED_SKILLS } from '@/components/studio/use-applied-skills';

export interface StyleAndSkillPicker {
  /** System style trigger/chip + style preset select, and (when
   * `showCreationSkillSelect`) the creation-skill Select+chips. Render it
   * once, wherever the caller's params panel wants it. */
  node: React.ReactNode;
  /** Up to 5 skills can be combined (mirrors `GenerationParams.skill_ids` server-side cap). */
  appliedSkillIds: string[];
  appliedStyleGalleryId: string | null;
  /** The look the author already committed to, so `PromptPolish` adds detail inside that style instead of proposing a different one. */
  styleHint: string;
  mentionableSkills: CreationSkillSummary[];
  applySkill: (skill: CreationSkillSummary) => void;
  /** Applied-skill chips / unlock dialog from `useAppliedSkills`. Video
   * (`showCreationSkillSelect: false`) renders these under `PromptField`
   * itself; audio keeps them inside `node`. */
  chips: React.ReactNode;
  unlockDialog: React.ReactNode;
}

/**
 * Style preset + system style ("画风库") picking, plus an optional creation
 * skill Select. Factored out of the old monolithic `GenerationStudio` so
 * `ImageGenerationStudio` can skip this hook entirely (template skills apply
 * from the prompt `@` menu via `useAppliedSkills`) and `VideoGenerationStudio`
 * can keep the gallery/preset half while dropping the skill Select — audio
 * is the remaining caller that still shows the full picker.
 *
 * Owns its own fetches and dropdown/dialog state; the caller only has to
 * merge whatever a pick applies (`onApplyParams`) into its own `prompt` /
 * `aspect` / `extra` state — that merge shape differs per operation type, so
 * it stays the caller's responsibility rather than living in here.
 */
export function useStyleAndSkillPicker({
  operation,
  initialStyleParams,
  initialStyleGalleryId,
  onApplyParams,
  showCreationSkillSelect = true,
  seedSkillId,
}: {
  operation: Operation;
  /** A style gallery entry's `params`, applied once on mount (from `?styleId=`). */
  initialStyleParams?: Record<string, unknown>;
  /** The catalogue id behind `initialStyleParams`; submitted as `style_gallery_id`. */
  initialStyleGalleryId?: string;
  onApplyParams: (params: Record<string, unknown>, detail?: CreationSkillDetail) => void;
  /** Audio still offers unlock-from-Select. Video applies skills only via
   * the prompt `@` menu, so it passes `false` and places chips itself. */
  showCreationSkillSelect?: boolean;
  /** Plaza / deep-link `?skillId=` — see `useAppliedSkills`. */
  seedSkillId?: string;
}): StyleAndSkillPicker {
  const t = useTranslations('remixPage');
  const tGallery = useTranslations('styleGallery');
  const tSkill = useTranslations('skillLibrary');
  const locale = useLocale() as Locale;
  const { status: sessionStatus } = useSession();

  const publicPresets = useResource<Page<StylePreset>>('/v1/style-presets');
  const minePresets = useResource<Page<StylePreset>>(
    sessionStatus === 'authenticated' ? '/v1/style-presets?mine=true' : null,
  );
  const presets = useMemo(() => {
    const byId = new Map<string, StylePreset>();
    for (const preset of publicPresets.data?.items ?? []) byId.set(preset.id, preset);
    for (const preset of minePresets.data?.items ?? []) byId.set(preset.id, preset);
    return [...byId.values()];
  }, [publicPresets.data, minePresets.data]);

  const { skills, mentionableSkills, appliedSkillIds, applySkill, chips, unlockDialog } =
    useAppliedSkills({ operation, onApplyParams, seedSkillId });

  const [presetId, setPresetId] = useState('');
  const [skillPickerValue, setSkillPickerValue] = useState('');
  const [styleGalleryOpen, setStyleGalleryOpen] = useState(false);
  const [appliedStyleGalleryId, setAppliedStyleGalleryId] = useState<string | null>(
    initialStyleGalleryId ?? null,
  );

  const applyPreset = (preset: StylePreset) => {
    onApplyParams(preset.params);
    // Best-effort usage counter; a preset is still fully applied locally if this fails.
    void api.post(`/v1/style-presets/${preset.id}/apply`).catch(() => undefined);
  };

  const applyStyleGalleryEntry = (entry: StyleGalleryEntry) => {
    onApplyParams(entry.params);
    setAppliedStyleGalleryId(entry.id);
    setStyleGalleryOpen(false);
    // Same best-effort shape as `applyPreset`: the usage counter is a nicety,
    // not a precondition for the pick actually landing in the form.
    void api.post(`/v1/style-gallery/${entry.id}/apply`).catch(() => undefined);
  };

  // Applied once: `initialStyleParams` is a mount-time seed from `?styleId=`,
  // not a value the form keeps tracking, so a functional `useState` initializer
  // (rather than an effect keyed on the prop) is what makes "once" precise.
  const [styleParamsApplied, setStyleParamsApplied] = useState(false);
  if (!styleParamsApplied && initialStyleParams) {
    setStyleParamsApplied(true);
    onApplyParams(initialStyleParams);
  }

  const countedInitialStyleApply = useRef(false);
  useEffect(() => {
    if (countedInitialStyleApply.current) return;
    if (!initialStyleGalleryId) return;
    if (sessionStatus !== 'authenticated') return;
    if (appliedStyleGalleryId !== initialStyleGalleryId) return;
    countedInitialStyleApply.current = true;
    void api.post(`/v1/style-gallery/${initialStyleGalleryId}/apply`).catch(() => undefined);
  }, [appliedStyleGalleryId, initialStyleGalleryId, sessionStatus]);

  const appliedStyle = useResource<StyleGalleryEntry>(
    appliedStyleGalleryId ? `/v1/style-gallery/${appliedStyleGalleryId}` : null,
  );

  const styleHint = [
    appliedStyle.data ? styleGalleryLabel(appliedStyle.data, locale) : '',
    ...appliedSkillIds.map((id) => skills.find((skill) => skill.id === id)?.title ?? ''),
  ]
    .filter(Boolean)
    .join('、');

  const node = (
    <>
      <div>
        <Button
          variant="secondary"
          icon={<IconSparkle className="size-4" />}
          onClick={() => setStyleGalleryOpen(true)}
          className="w-full"
        >
          {tGallery('trigger')}
        </Button>
        {appliedStyleGalleryId ? (
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setAppliedStyleGalleryId(null)}
              className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/12 py-0.5 pl-0.5 pr-2 text-xs font-medium text-primary"
            >
              <Poster
                src={appliedStyle.data?.cover_url}
                alt=""
                aspect="square"
                className="h-6 w-6 shrink-0 rounded"
              />
              {appliedStyle.data
                ? styleGalleryLabel(appliedStyle.data, locale)
                : tGallery('trigger')}
              <IconClose className="h-3 w-3" />
            </button>
          </div>
        ) : null}
      </div>

      {presets.length > 0 ? (
        <Select
          label={t('stylePreset')}
          hint={t('stylePresetHint')}
          value={presetId}
          onChange={(event) => {
            const value = event.target.value;
            const preset = presets.find((item) => item.id === value);
            if (preset) applyPreset(preset);
            // Transient: applying is a one-shot merge, not a persistent choice
            // the form keeps tracking, so the control resets to let the same
            // preset be reapplied after further edits.
            setPresetId('');
          }}
          options={[
            { value: '', label: t('stylePresetNone') },
            ...presets.map((preset) => ({ value: preset.id, label: preset.name })),
          ]}
        />
      ) : null}

      {showCreationSkillSelect && skills.length > 0 ? (
        <div>
          <Select
            label={t('skillPreset')}
            hint={t('skillPresetHint')}
            value={skillPickerValue}
            onChange={(event) => {
              const value = event.target.value;
              const skill = skills.find((item) => item.id === value);
              if (skill) applySkill(skill);
              // Transient, same reasoning as the style preset select above.
              setSkillPickerValue('');
            }}
            options={[
              { value: '', label: t('skillPresetNone') },
              // Already-applied skills and ones not built for this operation
              // (e.g. a video-only skill while composing an image) don't
              // clutter the picker — `applicable_operations` empty means any.
              ...skills
                .filter(
                  (skill) =>
                    !appliedSkillIds.includes(skill.id) &&
                    (!skill.applicable_operations ||
                      skill.applicable_operations.length === 0 ||
                      skill.applicable_operations.includes(operation)),
                )
                .map((skill) => ({
                  value: skill.id,
                  label:
                    skill.access_credits > 0 && !skill.viewer_unlocked
                      ? `${skill.title} · ${tSkill('priceCredits', { credits: skill.access_credits })}`
                      : skill.title,
                })),
            ]}
          />
          {chips}
        </div>
      ) : null}

      <StyleGalleryDialog
        open={styleGalleryOpen}
        onClose={() => setStyleGalleryOpen(false)}
        onSelect={applyStyleGalleryEntry}
      />

      {showCreationSkillSelect ? unlockDialog : null}
    </>
  );

  return {
    node,
    appliedSkillIds,
    appliedStyleGalleryId,
    styleHint,
    mentionableSkills,
    applySkill,
    chips,
    unlockDialog,
  };
}
