import { redirect } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { AdminLoginForm } from '@/components/admin/admin-login-form';
import { adminFetchOrNull, hasAdminSession } from '@/lib/api/admin-server';

export async function generateMetadata() {
  const t = await getTranslations('admin');
  return { title: t('loginTitle') };
}

/**
 * Console login, deliberately outside the console shell.
 *
 * It lives in its own route group so the shell's session guard cannot redirect
 * to a page that the guard itself protects.
 */
export default async function AdminLoginPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;

  if (await hasAdminSession()) {
    const session = await adminFetchOrNull<{ user_id: string }>('/v1/admin/auth/me');
    if (session) redirect(`/${locale}/admin`);
  }

  return <AdminLoginForm locale={locale} />;
}
