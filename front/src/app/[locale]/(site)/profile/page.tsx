import { redirect } from 'next/navigation';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Me } from '@/lib/api/types';

/**
 * `/profile` is the signed-in user's own page.
 *
 * It redirects to the handle URL rather than rendering a second copy, so the
 * owner and a visitor are always looking at the same route and the same code.
 */
export default async function MyProfilePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const me = await serverFetchOrNull<Me>('/v1/auth/me', { authenticated: true });

  if (!me?.profile) return <SignInPrompt />;
  redirect(`/${locale}/profile/${me.profile.handle}`);
}
