'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { UnlockDialog } from '@/components/marketplace/unlock-dialog';
import { ManageSkillDialog } from '@/components/skills/manage-skill-dialog';
import { SkillCard } from '@/components/skills/skill-card';
import { MediaLightbox } from '@/components/ui/media-lightbox';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { CreationSkillSummary } from '@/lib/api/types';

/**
 * The plaza's grid, split out from the (server) page component so clicking a
 * card can actually do something. Each `CreationSkillCategory` fans out to a
 * different action rather than one generic detail page, because these four
 * kinds of skill are consumed in four different places (no `/skills/[id]`
 * page exists):
 *
 * - `template` categories (`scene`/`lens`/`style`/`other`): unlock if paid
 *   and locked, then land in the video studio where the existing skill
 *   picker (`useStyleAndSkillPicker`) already lists it, now unlocked.
 * - `character`/`scene_asset`: these live on their own dedicated library
 *   page, not a generic apply flow.
 * - `cover_asset`: the owner gets `ManageSkillDialog` (the same edit surface
 *   a template skill's card would use); anyone else gets a straight look at
 *   the cover once unlocked (its thumbnail was never gated — only the right
 *   to *use* it is), or the same unlock dialog if it still is.
 */
export function SkillPlazaGrid({ skills }: { skills: CreationSkillSummary[] }) {
  const t = useTranslations('skillLibrary');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { user, requireAuth } = useSession();

  const [items, setItems] = useState(skills);
  const [pendingUnlock, setPendingUnlock] = useState<CreationSkillSummary | null>(null);
  const [managing, setManaging] = useState<CreationSkillSummary | null>(null);
  const [viewingCoverUrl, setViewingCoverUrl] = useState<string | null>(null);

  const markUnlocked = (skillId: string) => {
    setItems((current) =>
      current.map((item) => (item.id === skillId ? { ...item, viewer_unlocked: true } : item)),
    );
  };

  const applyAndEnterStudio = async (skill: CreationSkillSummary) => {
    try {
      await api.post(`/v1/skills/${skill.id}/apply`);
    } catch {
      // Best-effort usage ping; a miscount here must not block a user who
      // already has access from reaching the studio.
    }
    router.push('/create/new?mode=video_creation');
  };

  const openTemplateSkill = (skill: CreationSkillSummary) => {
    if (skill.access_credits > 0 && !skill.viewer_unlocked) {
      setPendingUnlock(skill);
      return;
    }
    void applyAndEnterStudio(skill);
  };

  const openCoverSkill = (skill: CreationSkillSummary) => {
    if (user && skill.author.user_id === user.id) {
      setManaging(skill);
      return;
    }
    if (skill.access_credits > 0 && !skill.viewer_unlocked) {
      setPendingUnlock(skill);
      return;
    }
    setViewingCoverUrl(skill.cover_url ?? null);
  };

  const openSkill = (skill: CreationSkillSummary) => {
    if (skill.category === 'character') {
      requireAuth({ label: skill.title, run: () => router.push('/create/characters') });
      return;
    }
    if (skill.category === 'scene_asset') {
      requireAuth({ label: skill.title, run: () => router.push('/create/scenes') });
      return;
    }
    if (skill.category === 'cover_asset') {
      requireAuth({ label: skill.title, run: () => openCoverSkill(skill) });
      return;
    }
    requireAuth({ label: skill.title, run: () => openTemplateSkill(skill) });
  };

  return (
    <>
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((skill) => (
          <SkillCard key={skill.id} skill={skill} locale={locale} onClick={() => openSkill(skill)} />
        ))}
      </ul>

      <UnlockDialog
        open={pendingUnlock !== null}
        onClose={() => setPendingUnlock(null)}
        path={pendingUnlock ? `/v1/skills/${pendingUnlock.id}/unlock` : ''}
        credits={pendingUnlock?.access_credits ?? 0}
        title={t('unlock')}
        confirm={t('unlockConfirm', {
          credits: pendingUnlock?.access_credits ?? 0,
          title: pendingUnlock?.title ?? '',
        })}
        onUnlocked={() => {
          const skill = pendingUnlock;
          setPendingUnlock(null);
          if (!skill) return;
          markUnlocked(skill.id);
          if (skill.category === 'cover_asset') {
            setViewingCoverUrl(skill.cover_url ?? null);
          } else {
            void applyAndEnterStudio({ ...skill, viewer_unlocked: true });
          }
        }}
      />

      {managing ? (
        <ManageSkillDialog
          skill={managing}
          onClose={() => setManaging(null)}
          onChanged={() => setManaging(null)}
        />
      ) : null}

      <MediaLightbox
        open={viewingCoverUrl !== null}
        onClose={() => setViewingCoverUrl(null)}
        src={viewingCoverUrl}
      />
    </>
  );
}
