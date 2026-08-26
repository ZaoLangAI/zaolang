import { redirect } from 'next/navigation';

/**
 * The cut editor moved to a chrome-less full-screen tab at
 * `(studio)/studio-editor/[cutId]`. This route stays only to carry forward
 * stale links/bookmarks to the old in-site URL.
 */
export default async function LegacyDramaCutRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; cutId: string }>;
  searchParams: Promise<{ draftId?: string }>;
}) {
  const { locale, cutId } = await params;
  const { draftId } = await searchParams;
  const query = draftId ? `?draftId=${encodeURIComponent(draftId)}` : '';
  redirect(`/${locale}/studio-editor/${cutId}${query}`);
}
