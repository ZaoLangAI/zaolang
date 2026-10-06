'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { IconSparkle } from '@/components/ui/icons';
import { Link, usePathname } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { CreationSkillDetail } from '@/lib/api/types';

/**
 * The style skill a plaza 用于角色 / 场景 / 道具创作 click carried onto a
 * library (`?skillId=`). Applied once here — `POST /v1/skills/{id}/apply` is
 * the usage counter, and it confirms the viewer may use it — then every card
 * link keeps the id so the 创作 slot panel preselects it.
 */
export function CarriedStyleSkill({ skillId }: { skillId: string }) {
  const t = useTranslations('assetWorkspace');
  const pathname = usePathname();
  const [applied, setApplied] = useState<{ id: string; title: string } | null>(null);
  const [failed, setFailed] = useState<{ id: string; message: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .post<CreationSkillDetail>(`/v1/skills/${encodeURIComponent(skillId)}/apply`)
      .then((detail) => {
        if (!cancelled) setApplied({ id: skillId, title: detail.title });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setFailed({
            id: skillId,
            message: isApiError(error) ? error.message : t('styleSkillCarriedFailed'),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [skillId, t]);

  const title = applied?.id === skillId ? applied.title : null;
  const error = failed?.id === skillId ? failed.message : null;
  if (!title && !error) return null;
  return (
    <p
      role="status"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-xs text-muted"
    >
      <IconSparkle className="size-3.5 text-primary" />
      <span className="min-w-0 break-words">
        {title ? t('styleSkillCarried', { title }) : error}
      </span>
      <Link href={pathname} className="text-text underline-offset-2 hover:underline">
        {t('styleSkillCarriedClear')}
      </Link>
    </p>
  );
}
