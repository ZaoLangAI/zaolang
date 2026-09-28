'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { UnlockDialog } from '@/components/marketplace/unlock-dialog';
import { Poster } from '@/components/media/poster';
import { IconClose } from '@/components/ui/icons';
import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import { useIsomorphicLayoutEffect } from '@/lib/motion';
import type { CreationSkillDetail, CreationSkillSummary, Operation, Page } from '@/lib/api/types';
import { isSkillMentionable } from '@/lib/skill-mention';
import { useResource } from '@/lib/use-resource';

/** Params a caller's own form already has a control for; anything else rides along as `extra`. */
export const KNOWN_PRESET_KEYS = new Set(['prompt', 'prompt_suffix', 'aspect_ratio']);

export const MAX_APPLIED_SKILLS = 5;

export type ApplySkillParams = (
  params: Record<string, unknown>,
  detail?: CreationSkillDetail,
) => void;

export interface AppliedSkills {
  skills: CreationSkillSummary[];
  mentionableSkills: CreationSkillSummary[];
  appliedSkillIds: string[];
  applySkill: (skill: CreationSkillSummary) => void;
  removeSkill: (skillId: string) => void;
  chips: React.ReactNode;
  unlockDialog: React.ReactNode;
}

/**
 * Fetch + apply/remove for template and image-asset `CreationSkill`s.
 * Shared by the audio style/skill picker (which still offers unlock from
 * its Select) and the image/video prompt `@` menu (which only lists free
 * or already-purchased skills that apply to the current operation).
 */
export function useAppliedSkills({
  operation,
  onApplyParams,
  seedSkillId,
}: {
  operation: Operation;
  onApplyParams: ApplySkillParams;
  /** Plaza / deep-link `?skillId=` — apply once on mount so usage is
   * counted here, not also on the plaza CTA. */
  seedSkillId?: string;
}): AppliedSkills {
  const tSkill = useTranslations('skillLibrary');
  const { notify } = useToast();
  const { status: sessionStatus } = useSession();

  const publicTemplates = useResource<Page<CreationSkillSummary>>(
    '/v1/skills/public?content_type=template&limit=60',
  );
  const publicImageAssets = useResource<Page<CreationSkillSummary>>(
    '/v1/skills/public?content_type=image_asset&limit=60',
  );
  const mineSkills = useResource<Page<CreationSkillSummary>>(
    sessionStatus === 'authenticated' ? '/v1/skills' : null,
  );
  const skills = useMemo(() => {
    const byId = new Map<string, CreationSkillSummary>();
    for (const skill of publicTemplates.data?.items ?? []) byId.set(skill.id, skill);
    for (const skill of publicImageAssets.data?.items ?? []) byId.set(skill.id, skill);
    for (const skill of mineSkills.data?.items ?? []) byId.set(skill.id, skill);
    return [...byId.values()];
  }, [publicTemplates.data, publicImageAssets.data, mineSkills.data]);

  const mentionableSkills = useMemo(
    () => skills.filter((skill) => isSkillMentionable(skill, operation)),
    [skills, operation],
  );

  const [appliedSkillIds, setAppliedSkillIds] = useState<string[]>([]);
  const [pendingUnlockSkill, setPendingUnlockSkill] = useState<CreationSkillSummary | null>(null);
  const onApplyParamsRef = useRef(onApplyParams);
  // Synced after commit rather than assigned during render (refs must not be
  // written while rendering) — same pattern as `use-overlay-transition.ts`.
  useIsomorphicLayoutEffect(() => {
    onApplyParamsRef.current = onApplyParams;
  });
  const seededSkillIdRef = useRef<string | null>(null);

  const applyUnlockedSkill = async (skill: CreationSkillSummary) => {
    try {
      const detail = await api.post<CreationSkillDetail>(`/v1/skills/${skill.id}/apply`);
      onApplyParamsRef.current(detail.params ?? {}, detail);
      setAppliedSkillIds((current) =>
        current.includes(skill.id) || current.length >= MAX_APPLIED_SKILLS
          ? current
          : [...current, skill.id],
      );
    } catch (caught) {
      notify(caught instanceof ApiError ? caught.message : tSkill('applyLocked'), 'error');
    }
  };

  useEffect(() => {
    if (!seedSkillId || seededSkillIdRef.current === seedSkillId) return;
    seededSkillIdRef.current = seedSkillId;
    void applyUnlockedSkill({
      id: seedSkillId,
      title: '',
      description: '',
      category: 'style',
      author: { user_id: '', handle: '', display_name: '' },
      visibility: 'public',
      status: 'published',
      usage_count: 0,
      access_credits: 0,
      viewer_unlocked: true,
      has_variables: false,
      created_at: '',
    });
    // Intentionally seed once per `skillId`; `onApplyParams` is read from a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedSkillId]);

  const applySkill = (skill: CreationSkillSummary) => {
    if (appliedSkillIds.includes(skill.id) || appliedSkillIds.length >= MAX_APPLIED_SKILLS) return;
    if (skill.access_credits > 0 && !skill.viewer_unlocked) {
      setPendingUnlockSkill(skill);
      return;
    }
    void applyUnlockedSkill(skill);
  };

  const removeSkill = (skillId: string) => {
    setAppliedSkillIds((current) => current.filter((id) => id !== skillId));
  };

  const chips =
    appliedSkillIds.length > 0 ? (
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
    ) : null;

  const unlockDialog = (
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
  );

  return {
    skills,
    mentionableSkills,
    appliedSkillIds,
    applySkill,
    removeSkill,
    chips,
    unlockDialog,
  };
}
