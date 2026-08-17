'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { UnlockDialog } from '@/components/marketplace/unlock-dialog';
import { StyleGalleryDialog } from '@/components/studio/style-gallery-dialog';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/field';
import { IconClose, IconSparkle } from '@/components/ui/icons';
import { useToast } from '@/components/ui/toast';
import { Poster } from '@/components/media/poster';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
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

/** Params a caller's own form already has a control for; anything else rides along as `extra`. */
export const KNOWN_PRESET_KEYS = new Set(['prompt', 'prompt_suffix', 'aspect_ratio']);

// Distinct from the ordered set below (which is what actually travels to the
// job): the picker itself resets after each pick so it's ready for the next one.
const MAX_APPLIED_SKILLS = 5;

export interface StyleAndSkillPicker {
  /** The whole block — system style trigger/chip, style preset select, creation skill select+chips. Render it once, wherever the caller's params panel wants it. */
  node: React.ReactNode;
  /** Up to 5 skills can be combined (mirrors `GenerationParams.skill_ids` server-side cap). */
  appliedSkillIds: string[];
  appliedStyleGalleryId: string | null;
  /** The look the author already committed to, so `PromptPolish` adds detail inside that style instead of proposing a different one. */
  styleHint: string;
}

/**
 * Style preset + creation skill + system style ("画风库") picking, factored
 * out of the old monolithic `GenerationStudio` so `ImageGenerationStudio` can
 * simply not use this hook at all (see `zaolang-frontend-ui` invariants) while
 * `VideoGenerationStudio` and `AudioGenerationStudio` keep the exact same
 * three controls and requests they had before the split.
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
}: {
  operation: Operation;
  /** A style gallery entry's `params`, applied once on mount (from `?styleId=`). */
  initialStyleParams?: Record<string, unknown>;
  /** The catalogue id behind `initialStyleParams`; submitted as `style_gallery_id`. */
  initialStyleGalleryId?: string;
  onApplyParams: (params: Record<string, unknown>) => void;
}): StyleAndSkillPicker {
  const t = useTranslations('remixPage');
  const tGallery = useTranslations('styleGallery');
  const tSkill = useTranslations('skillLibrary');
  const { notify } = useToast();
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

  const publicSkills = useResource<Page<CreationSkillSummary>>('/v1/skills/public');
  const mineSkills = useResource<Page<CreationSkillSummary>>(
    sessionStatus === 'authenticated' ? '/v1/skills' : null,
  );
  const skills = useMemo(() => {
    const byId = new Map<string, CreationSkillSummary>();
    for (const skill of publicSkills.data?.items ?? []) byId.set(skill.id, skill);
    for (const skill of mineSkills.data?.items ?? []) byId.set(skill.id, skill);
    return [...byId.values()];
  }, [publicSkills.data, mineSkills.data]);

  const [presetId, setPresetId] = useState('');
  const [skillPickerValue, setSkillPickerValue] = useState('');
  const [styleGalleryOpen, setStyleGalleryOpen] = useState(false);
  const [appliedStyleGalleryId, setAppliedStyleGalleryId] = useState<string | null>(
    initialStyleGalleryId ?? null,
  );
  const [appliedSkillIds, setAppliedSkillIds] = useState<string[]>([]);
  const [pendingUnlockSkill, setPendingUnlockSkill] = useState<CreationSkillSummary | null>(null);

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

  const applySkill = (skill: CreationSkillSummary) => {
    if (appliedSkillIds.includes(skill.id) || appliedSkillIds.length >= MAX_APPLIED_SKILLS) return;
    if (skill.access_credits > 0 && !skill.viewer_unlocked) {
      setPendingUnlockSkill(skill);
      return;
    }
    void applyUnlockedSkill(skill);
  };

  const applyUnlockedSkill = async (skill: CreationSkillSummary) => {
    try {
      const detail = await api.post<CreationSkillDetail>(`/v1/skills/${skill.id}/apply`);
      onApplyParams(detail.params ?? {});
      setAppliedSkillIds((current) => [...current, skill.id]);
    } catch (caught) {
      notify(caught instanceof ApiError ? caught.message : tSkill('applyLocked'), 'error');
    }
  };

  const removeSkill = (skillId: string) => {
    setAppliedSkillIds((current) => current.filter((id) => id !== skillId));
  };

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

      {skills.length > 0 ? (
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
          {appliedSkillIds.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {appliedSkillIds.flatMap((id) => {
                const skill = skills.find((item) => item.id === id);
                if (!skill) return [];
                return [
                  <button
                    key={id}
                    type="button"
                    onClick={() => removeSkill(id)}
                    className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/12 py-0.5 pl-0.5 pr-2 text-xs font-medium text-primary"
                  >
                    {/* A real preview, not just a label, so picking a skill shows
                        what it actually does before the job even runs — and a
                        video-based skill plays instead of a broken frame. */}
                    <Poster
                      src={skill.cover_url}
                      alt=""
                      aspect="square"
                      mediaType={skill.cover_media_type}
                      className="h-6 w-6 shrink-0 rounded"
                    />
                    {skill.title}
                    <IconClose className="h-3 w-3" />
                  </button>,
                ];
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      <StyleGalleryDialog
        open={styleGalleryOpen}
        onClose={() => setStyleGalleryOpen(false)}
        onSelect={applyStyleGalleryEntry}
      />

      <UnlockDialog
        open={pendingUnlockSkill !== null}
        onClose={() => setPendingUnlockSkill(null)}
        path={pendingUnlockSkill ? `/v1/skills/${pendingUnlockSkill.id}/unlock` : '/v1/skills'}
        credits={pendingUnlockSkill?.access_credits ?? 0}
        title={tSkill('unlock')}
        confirm={tSkill('unlockConfirm', {
          credits: pendingUnlockSkill?.access_credits ?? 0,
          title: pendingUnlockSkill?.title ?? '',
        })}
        onUnlocked={() => {
          const skill = pendingUnlockSkill;
          setPendingUnlockSkill(null);
          if (skill) void applyUnlockedSkill({ ...skill, viewer_unlocked: true });
        }}
      />
    </>
  );

  return { node, appliedSkillIds, appliedStyleGalleryId, styleHint };
}
