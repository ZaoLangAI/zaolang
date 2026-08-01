'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Avatar } from '@/components/work/avatar';
import { Button } from '@/components/ui/button';
import { IconGear } from '@/components/ui/icons';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import type { PublicProfile } from '@/lib/api/types';

export function ProfileHeader({ profile }: { profile: PublicProfile }) {
  const t = useTranslations('profilePage');
  const router = useRouter();
  const { requireAuth } = useSession();

  const [following, setFollowing] = useState(profile.viewer_following);
  const [busy, setBusy] = useState(false);

  const toggleFollow = () =>
    requireAuth({
      label: t('follow'),
      run: async () => {
        setBusy(true);
        const next = !following;
        try {
          if (next) await api.post(`/v1/users/${profile.user_id}/follow`);
          else await api.delete(`/v1/users/${profile.user_id}/follow`);
          setFollowing(next);
        } finally {
          setBusy(false);
        }
      },
    });

  return (
    <header className="relative overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface">
      <div className="poster-scrim relative h-44 bg-surface-soft sm:h-56">
        {profile.cover_url ? (
          <Image
            src={profile.cover_url}
            alt=""
            fill
            sizes="100vw"
            priority
            className="object-cover"
          />
        ) : null}
      </div>

      <div className="relative -mt-12 flex flex-wrap items-end justify-between gap-4 px-5 pb-5 sm:px-6">
        <div className="flex items-end gap-4">
          <Avatar
            src={profile.avatar_url}
            name={profile.display_name}
            size="lg"
            className="size-20 border-2 border-surface text-2xl"
          />
          <div className="pb-1">
            <p className="eyebrow">{t('eyebrow')}</p>
            <h1 className="mt-0.5 text-2xl font-bold tracking-tight sm:text-3xl">
              {profile.display_name}
            </h1>
            <p className="mt-1 text-xs text-muted">
              @{profile.handle}
              {profile.location ? ` · ${profile.location}` : ''}
            </p>
          </div>
        </div>

        {profile.is_self ? (
          <Button
            variant="secondary"
            icon={<IconGear className="size-4" />}
            onClick={() => router.push('/profile/settings')}
          >
            {t('editProfile')}
          </Button>
        ) : (
          <Button
            variant={following ? 'secondary' : 'primary'}
            loading={busy}
            onClick={toggleFollow}
          >
            {following ? t('following') : t('follow')}
          </Button>
        )}
      </div>
    </header>
  );
}
