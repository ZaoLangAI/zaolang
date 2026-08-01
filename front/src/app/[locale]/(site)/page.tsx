import { redirect } from '@/i18n/navigation';

/** Discover is the landing experience; `/` only exists to point at it. */
export default async function LocaleHome({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  redirect({ href: '/discover', locale });
}
