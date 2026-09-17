'use client';

import { useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { UnlockDialog } from '@/components/marketplace/unlock-dialog';
import { useToast } from '@/components/ui/toast';
import type { CreationSkillSummary, Page } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

export const MAX_REFERENCED_SKILLS = 5;

/**
 * Data layer shared by the `@`-mention menu and the referenced-skill chip
 * row: the merged public/own skill library, plus the paid-unlock gate a
 * skill reference has to pass before its id can join `referencedSkillIds`.
 *
 * Split out of the old `SkillReferencePicker` card rail so both the menu
 * (picking a *new* reference) and the chip row (showing ones already
 * picked) can share one fetch and one `UnlockDialog` instance instead of
 * each re-implementing the unlock flow.
 */
export function useSkillReferences() {
  const t = useTranslations('scriptStudio');
  const { notify } = useToast();
  const { status: sessionStatus } = useSession();
  const [pendingUnlock, setPendingUnlock] = useState<{
    skill: CreationSkillSummary;
    onGranted: () => void;
  } | null>(null);

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

  /**
   * Grants `onGranted` immediately for a free (or already-unlocked) skill;
   * for a locked paid one, routes through `UnlockDialog` first and only
   * grants once the unlock actually succeeds.
   */
  const requestReference = (skill: CreationSkillSummary, onGranted: () => void) => {
    if (skill.access_credits > 0 && !skill.viewer_unlocked) {
      setPendingUnlock({ skill, onGranted });
      return;
    }
    onGranted();
  };

  const unlockDialog = (
    <UnlockDialog
      open={pendingUnlock !== null}
      onClose={() => setPendingUnlock(null)}
      path={pendingUnlock ? `/v1/skills/${pendingUnlock.skill.id}/unlock` : '/v1/skills'}
      credits={pendingUnlock?.skill.access_credits ?? 0}
      title={t('referenceSkillUnlock')}
      confirm={t('referenceSkillUnlockConfirm', {
        credits: pendingUnlock?.skill.access_credits ?? 0,
        title: pendingUnlock?.skill.title ?? '',
      })}
      onUnlocked={() => {
        const granted = pendingUnlock;
        setPendingUnlock(null);
        if (granted) {
          granted.onGranted();
          notify(t('referenceSkillUnlocked', { title: granted.skill.title }), 'success');
        }
      }}
    />
  );

  return { skills, requestReference, unlockDialog };
}
