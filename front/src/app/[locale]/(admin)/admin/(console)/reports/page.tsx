import { redirect } from 'next/navigation';

/**
 * The reports console merged into `/admin/moderation` as a tab (they act on
 * the same works and share the queue's `open_report_count` signal) — this
 * redirect keeps the old bookmarked/linked URL working.
 */
export default async function AdminReportsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  redirect(`/${locale}/admin/moderation?tab=reports`);
}
