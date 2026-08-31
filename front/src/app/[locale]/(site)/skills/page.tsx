import { getTranslations } from 'next-intl/server';

import { SkillPlazaGrid } from '@/components/skills/skill-plaza-grid';
import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import { serverFetchOrNull } from '@/lib/api/server';
import type { CreationSkillCategory, CreationSkillSummary, Page } from '@/lib/api/types';
import { cn } from '@/lib/cn';

type ContentType = 'template' | 'image_asset';

// Two-tier filter: a "content type" (template vs. image asset) picks the
// side of the marketplace, then `CATEGORIES_BY_CONTENT_TYPE` narrows within
// it — see `skill_library.list_public`'s own `IMAGE_ASSET_SKILL_CATEGORIES`
// split. `character` only ever shows up inside `image_asset`: it browses
// through `/create/characters` (own publish/portrait-consent flow), not a
// generic "apply" click here.
const CATEGORIES_BY_CONTENT_TYPE: Record<ContentType, CreationSkillCategory[]> = {
  template: ['scene', 'lens', 'style', 'other'],
  image_asset: ['character', 'scene_asset', 'cover_asset'],
};

const CATEGORY_LABEL_KEY: Record<
  CreationSkillCategory,
  | 'categoryScene'
  | 'categoryLens'
  | 'categoryStyle'
  | 'categoryCharacter'
  | 'categorySceneAsset'
  | 'categoryCoverAsset'
  | 'categoryOther'
> = {
  scene: 'categoryScene',
  lens: 'categoryLens',
  style: 'categoryStyle',
  character: 'categoryCharacter',
  scene_asset: 'categorySceneAsset',
  cover_asset: 'categoryCoverAsset',
  other: 'categoryOther',
};

export async function generateMetadata() {
  const t = await getTranslations('skillLibrary');
  return { title: t('plazaTitle'), description: t('plazaSubtitle') };
}

export default async function SkillLibraryPage({
  searchParams,
}: {
  searchParams: Promise<{ contentType?: string; category?: string; access?: string }>;
}) {
  const { contentType, category, access } = await searchParams;
  const t = await getTranslations('skillLibrary');
  const activeContentType: ContentType = contentType === 'image_asset' ? 'image_asset' : 'template';
  const categories = CATEGORIES_BY_CONTENT_TYPE[activeContentType];
  const activeCategory = (categories as readonly string[]).includes(category ?? '')
    ? (category as CreationSkillCategory)
    : undefined;
  const activeAccess = access === 'free' || access === 'paid' ? access : undefined;

  const page = await serverFetchOrNull<Page<CreationSkillSummary>>('/v1/skills/public', {
    query: {
      content_type: activeContentType,
      category: activeCategory,
      access: activeAccess,
      limit: 48,
    },
    revalidate: 60,
  });
  const skills = page?.items ?? [];

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-8 px-4 py-8 sm:px-6">
      <div>
        <p className="eyebrow">{t('plazaEyebrow')}</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">{t('plazaTitle')}</h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted">{t('plazaSubtitle')}</p>
      </div>

      <div className="flex flex-col gap-2">
        <nav aria-label={t('filterContentType')} className="flex flex-wrap gap-2">
          <ContentTypeLink
            label={t('contentTypeTemplate')}
            active={activeContentType === 'template'}
            contentType="template"
            access={activeAccess}
          />
          <ContentTypeLink
            label={t('contentTypeImageAsset')}
            active={activeContentType === 'image_asset'}
            contentType="image_asset"
            access={activeAccess}
          />
        </nav>
        <nav aria-label={t('filterCategory')} className="flex flex-wrap gap-2">
          <CategoryLink
            label={t('categoryAll')}
            active={!activeCategory}
            contentType={activeContentType}
            category={undefined}
            access={activeAccess}
          />
          {categories.map((value) => (
            <CategoryLink
              key={value}
              label={t(CATEGORY_LABEL_KEY[value])}
              active={activeCategory === value}
              contentType={activeContentType}
              category={value}
              access={activeAccess}
            />
          ))}
        </nav>
        <nav aria-label={t('filterAccess')} className="flex flex-wrap gap-2">
          <AccessLink
            label={t('accessAll')}
            active={!activeAccess}
            contentType={activeContentType}
            category={activeCategory}
            access={undefined}
          />
          <AccessLink
            label={t('accessFree')}
            active={activeAccess === 'free'}
            contentType={activeContentType}
            category={activeCategory}
            access="free"
          />
          <AccessLink
            label={t('accessPaid')}
            active={activeAccess === 'paid'}
            contentType={activeContentType}
            category={activeCategory}
            access="paid"
          />
        </nav>
      </div>

      <section>
        <SectionHeading title={t('plazaTitle')} />
        {skills.length > 0 ? (
          <SkillPlazaGrid skills={skills} />
        ) : (
          <EmptyState title={t('empty')} description={t('emptyHint')} />
        )}
      </section>
    </div>
  );
}

function skillsHref(
  contentType: ContentType,
  category?: CreationSkillCategory,
  access?: 'free' | 'paid',
) {
  const query = new URLSearchParams();
  if (contentType === 'image_asset') query.set('contentType', contentType);
  if (category) query.set('category', category);
  if (access) query.set('access', access);
  const suffix = query.toString();
  return suffix ? `/skills?${suffix}` : '/skills';
}

function ContentTypeLink({
  label,
  active,
  contentType,
  access,
}: {
  label: string;
  active: boolean;
  contentType: ContentType;
  access?: 'free' | 'paid';
}) {
  return (
    <Link
      href={skillsHref(contentType, undefined, access)}
      className={cn(
        'rounded-full border px-3.5 py-1.5 text-xs font-semibold transition-colors',
        active
          ? 'border-primary bg-primary/12 text-primary'
          : 'border-border text-muted hover:border-border-strong hover:text-text',
      )}
    >
      {label}
    </Link>
  );
}

function CategoryLink({
  label,
  active,
  contentType,
  category,
  access,
}: {
  label: string;
  active: boolean;
  contentType: ContentType;
  category: CreationSkillCategory | undefined;
  access?: 'free' | 'paid';
}) {
  return (
    <Link
      href={skillsHref(contentType, category, access)}
      className={cn(
        'rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors',
        active
          ? 'border-primary bg-primary/12 text-primary'
          : 'border-border text-muted hover:border-border-strong hover:text-text',
      )}
    >
      {label}
    </Link>
  );
}

function AccessLink({
  label,
  active,
  contentType,
  category,
  access,
}: {
  label: string;
  active: boolean;
  contentType: ContentType;
  category: CreationSkillCategory | undefined;
  access?: 'free' | 'paid';
}) {
  return (
    <Link
      href={skillsHref(contentType, category, access)}
      className={cn(
        'rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors',
        active
          ? 'border-primary bg-primary/12 text-primary'
          : 'border-border text-muted hover:border-border-strong hover:text-text',
      )}
    >
      {label}
    </Link>
  );
}
