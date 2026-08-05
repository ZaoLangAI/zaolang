import { getLocale, getTranslations } from 'next-intl/server';

import { SkillCard } from '@/components/skills/skill-card';
import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { serverFetchOrNull } from '@/lib/api/server';
import type { CreationSkillCategory, CreationSkillSummary, Page } from '@/lib/api/types';
import { cn } from '@/lib/cn';

const CATEGORIES: CreationSkillCategory[] = ['scene', 'lens', 'style', 'other'];

const CATEGORY_LABEL_KEY: Record<
  CreationSkillCategory,
  'categoryScene' | 'categoryLens' | 'categoryStyle' | 'categoryOther'
> = {
  scene: 'categoryScene',
  lens: 'categoryLens',
  style: 'categoryStyle',
  other: 'categoryOther',
};

export async function generateMetadata() {
  const t = await getTranslations('skillLibrary');
  return { title: t('plazaTitle'), description: t('plazaSubtitle') };
}

export default async function SkillLibraryPage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string }>;
}) {
  const { category } = await searchParams;
  const t = await getTranslations('skillLibrary');
  const locale = (await getLocale()) as Locale;
  const activeCategory = (CATEGORIES as readonly string[]).includes(category ?? '')
    ? (category as CreationSkillCategory)
    : undefined;

  const page = await serverFetchOrNull<Page<CreationSkillSummary>>('/v1/skills/public', {
    query: { category: activeCategory, limit: 48 },
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

      <nav aria-label={t('filterCategory')} className="flex flex-wrap gap-2">
        <CategoryLink label={t('categoryAll')} active={!activeCategory} category={undefined} />
        {CATEGORIES.map((value) => (
          <CategoryLink
            key={value}
            label={t(CATEGORY_LABEL_KEY[value])}
            active={activeCategory === value}
            category={value}
          />
        ))}
      </nav>

      <section>
        <SectionHeading title={t('plazaTitle')} />
        {skills.length > 0 ? (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {skills.map((skill) => (
              <SkillCard key={skill.id} skill={skill} locale={locale} />
            ))}
          </ul>
        ) : (
          <EmptyState title={t('empty')} description={t('emptyHint')} />
        )}
      </section>
    </div>
  );
}

function CategoryLink({
  label,
  active,
  category,
}: {
  label: string;
  active: boolean;
  category: CreationSkillCategory | undefined;
}) {
  return (
    <Link
      href={category ? `/skills?category=${category}` : '/skills'}
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