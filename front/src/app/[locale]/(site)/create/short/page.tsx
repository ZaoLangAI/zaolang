import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';

import { PublishKit } from '@/components/shortform/publish-kit';
import { ShortformStudio } from '@/components/shortform/shortform-studio';
import type { Caption } from '@/components/shortform/caption-composer';
import { EmptyState, PageHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Character, Draft, Page, PublicationIntent, ShortformProfiles, Series } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('shortform');
  return { title: t('title'), description: t('subtitle') };
}

/**
 * The short-video chain, in two states.
 *
 * Without a draft it is the studio: frame, length and caption decided against
 * the delivery spec before a credit is spent. With one it is the export kit,
 * which is where the chain ends — the platform produces the file and the
 * caption, and the creator posts them.
 */
export default async function ShortformPage({
  searchParams,
}: {
  searchParams: Promise<{ draftId?: string }>;
}) {
  const { draftId } = await searchParams;
  const t = await getTranslations('shortform');

  // Public and shared by every visitor, so it is cached rather than fetched per
  // request; the numbers change when an operator edits the config centre.
  const profiles = await serverFetchOrNull<ShortformProfiles>('/v1/shortform/profiles', {
    revalidate: 300,
  });

  if (!profiles || profiles.profiles.length === 0) {
    return (
      <Shell title={t('title')} subtitle={t('subtitle')} eyebrow={t('eyebrow')}>
        <EmptyState title={t('unavailable')} description={t('unavailableHint')} />
      </Shell>
    );
  }

  if (!draftId) {
    // Null (rather than empty) means the visitor is not signed in, which is
    // the studio's cue to hide the series/character section entirely instead
    // of showing an empty one nobody signed-out could act on.
    const series = await serverFetchOrNull<Series[]>('/v1/series', { authenticated: true });
    const characters = await serverFetchOrNull<Character[]>('/v1/characters', {
      authenticated: true,
    });
    return (
      <Shell title={t('title')} subtitle={t('subtitle')} eyebrow={t('eyebrow')}>
        <ShortformStudio profiles={profiles} series={series} characters={characters} />
      </Shell>
    );
  }

  const draft = await serverFetchOrNull<Draft>(`/v1/drafts/${draftId}`, { authenticated: true });
  if (!draft) notFound();

  const profile =
    profiles.profiles.find((item) => item.key === profileKeyOf(draft)) ??
    profiles.profiles.find((item) => item.key === profiles.default_profile) ??
    profiles.profiles[0]!;

  const intents = draft.published_work_id
    ? await serverFetchOrNull<Page<PublicationIntent>>(
        `/v1/works/${draft.published_work_id}/publications`,
        { authenticated: true },
      )
    : null;

  return (
    <Shell title={t('kitTitle')} subtitle={t('kitHint')} eyebrow={t('eyebrow')}>
      <PublishKit
        draft={draft}
        profile={profile}
        initialIntents={intents?.items ?? []}
        initialCaption={captionOf(draft)}
      />
    </Shell>
  );
}

function Shell({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-6 sm:px-6">
      <PageHeading eyebrow={eyebrow} title={title} description={subtitle} />
      {children}
    </div>
  );
}

function profileKeyOf(draft: Draft): string | null {
  const key = draft.params?.shortform_profile;
  return typeof key === 'string' ? key : null;
}

/**
 * The caption written in the studio, read back off the draft.
 *
 * `params` is a free-form blob, so every field is proved rather than trusted;
 * the draft's own title is the fallback for a clip that came from the ordinary
 * studio and is only now being prepared for a vertical feed.
 */
function captionOf(draft: Draft): Caption {
  const stored = draft.params?.shortform_caption;
  const record =
    typeof stored === 'object' && stored !== null ? (stored as Record<string, unknown>) : {};
  const hashtags = Array.isArray(record.hashtags)
    ? record.hashtags.filter((tag): tag is string => typeof tag === 'string')
    : [];

  return {
    title: typeof record.title === 'string' && record.title ? record.title : (draft.title ?? ''),
    description:
      typeof record.description === 'string' && record.description
        ? record.description
        : (draft.description ?? ''),
    hashtags,
  };
}
