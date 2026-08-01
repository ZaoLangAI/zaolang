import { getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { NotificationList } from '@/components/notifications/notification-list';
import { PageHeading } from '@/components/ui/primitives';
import { isSignedIn, serverFetchOrNull } from '@/lib/api/server';
import type { Notification, Page } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('notificationsPage');
  return { title: t('title'), description: t('subtitle') };
}

export default async function NotificationsPage() {
  const t = await getTranslations('notificationsPage');
  if (!(await isSignedIn())) return <SignInPrompt />;

  const notifications = await serverFetchOrNull<Page<Notification>>('/v1/notifications', {
    authenticated: true,
    query: { limit: 50 },
  });
  if (!notifications) return <SignInPrompt />;

  return (
    <div className="mx-auto flex w-full max-w-[860px] flex-col gap-6 px-4 py-8 sm:px-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <NotificationList initial={notifications.items} />
    </div>
  );
}
