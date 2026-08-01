import { redirect } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { AdminSessionProvider, type AdminSession } from '@/components/admin/admin-session-provider';
import { AdminSidebar } from '@/components/admin/admin-sidebar';
import { adminFetchOrNull, hasAdminSession } from '@/lib/api/admin-server';

export async function generateMetadata() {
  const t = await getTranslations('admin');
  return { title: { default: t('console'), template: `%s · ${t('consoleShort')}` } };
}

/**
 * Console shell.
 *
 * The session is resolved here, once, so no console page can render without a
 * valid admin token: a missing or rejected session redirects to the console's
 * own login page rather than the consumer one.
 */
export default async function AdminLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  const session = (await hasAdminSession())
    ? await adminFetchOrNull<AdminSession>('/v1/admin/auth/me')
    : null;
  if (!session) redirect(`/${locale}/admin/login`);

  return (
    <AdminSessionProvider session={session}>
      <div className="flex min-h-dvh">
        <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 lg:block">
          <AdminSidebar />
        </aside>
        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6">{children}</main>
      </div>
    </AdminSessionProvider>
  );
}
