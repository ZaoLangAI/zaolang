'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { UnlockDialog } from '@/components/marketplace/unlock-dialog';
import { ManageSkillDialog } from '@/components/skills/manage-skill-dialog';
import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { MediaLightbox } from '@/components/ui/media-lightbox';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import { IconCheck, IconCopy, IconLock } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { CreationSkillCategory, CreationSkillDetail, CreationSkillSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount } from '@/lib/format';
import { useResource } from '@/lib/use-resource';

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

// The flat `prompt`/`prompt_suffix`/`aspect_ratio` shape every template
// category (`scene`/`lens`/`style`/`other`) uses — see
// `skill_library.catalog.CatalogSkill.params_json`. `character`/`scene_asset`
// store a nested `reference_assets` bundle instead (not meaningful to dump as
// a flat key/value list here), and `cover_asset` has no params at all — its
// "core content" is the cover image itself, already shown above unlocked.
const TEMPLATE_CATEGORIES = new Set<CreationSkillCategory>(['scene', 'lens', 'style', 'other']);

const PARAM_LABEL_KEY: Record<string, 'paramPromptLabel' | 'paramPromptSuffixLabel' | 'paramAspectRatioLabel'> = {
  prompt: 'paramPromptLabel',
  prompt_suffix: 'paramPromptSuffixLabel',
  aspect_ratio: 'paramAspectRatioLabel',
};

/**
 * The skill library's one detail surface, opened from every card in
 * `SkillPlazaGrid` regardless of category. Viewing is free for anyone —
 * `GET /v1/skills/{id}` already returns full content for a free/unlocked
 * skill and an empty `params` for a locked paid one (`_detail()` in
 * `app/api/v1/skills.py`); this component only has to render that gate, not
 * enforce it. Every action that actually *does* something (unlock, apply,
 * navigate to a dedicated library, manage) is gated behind `requireAuth` at
 * click time instead, so an anonymous visitor can still read the whole card.
 */
export function SkillDetailDialog({
  skill,
  onClose,
  onUnlocked,
}: {
  /** `null` closes the dialog. Kept mounted regardless (see `Dialog`'s own
   * exit-animation contract) so the panel fades out on its last content
   * instead of blanking instantly. */
  skill: CreationSkillSummary | null;
  onClose: () => void;
  /** Bubbles a successful unlock up so the grid's own list can flip that
   * card's badge without waiting for a full page refetch. */
  onUnlocked: (skillId: string) => void;
}) {
  const t = useTranslations('skillLibrary');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { user, requireAuth } = useSession();

  const [pendingUnlock, setPendingUnlock] = useState(false);
  const [managing, setManaging] = useState(false);
  const [viewingCoverUrl, setViewingCoverUrl] = useState<string | null>(null);
  const [forceUnlocked, setForceUnlocked] = useState(false);

  const detail = useResource<CreationSkillDetail>(skill ? `/v1/skills/${skill.id}` : null);
  const data = detail.data ?? skill;
  const unlocked = forceUnlocked || Boolean(data?.viewer_unlocked);
  const locked = Boolean(skill) && (skill?.access_credits ?? 0) > 0 && !unlocked;

  const close = () => {
    onClose();
    setPendingUnlock(false);
    setForceUnlocked(false);
  };

  const applyAndEnterStudio = async () => {
    if (!skill) return;
    try {
      await api.post(`/v1/skills/${skill.id}/apply`);
    } catch {
      // Best-effort usage ping; a miscount here must not block a user who
      // already has access from reaching the studio.
    }
    close();
    router.push('/create/new?mode=video_creation');
  };

  const goLibrary = (path: '/create/characters' | '/create/scenes') => {
    if (!skill) return;
    requireAuth({ label: skill.title, run: () => router.push(path) });
  };

  return (
    <>
      <Dialog open={skill !== null} onClose={close} title={skill?.title ?? ''} size="lg">
        {skill ? (
          <div className="flex flex-col gap-6">
            <Poster
              src={data?.cover_url ?? skill.cover_url}
              alt={skill.title}
              aspect="video"
              mediaType={data?.cover_media_type ?? skill.cover_media_type}
            />

            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="amber">{t(CATEGORY_LABEL_KEY[skill.category])}</Badge>
              {skill.access_credits > 0 ? (
                <Badge tone={unlocked ? 'success' : 'primary'}>
                  {t('priceCredits', { credits: skill.access_credits })}
                </Badge>
              ) : (
                <Badge tone="success">{t('priceFree')}</Badge>
              )}
            </div>

            <div className="flex items-center justify-between text-xs text-muted">
              <span>{t('byAuthor', { name: skill.author.display_name })}</span>
              <span className="tabular">
                {t('usageCount', { count: formatCount(skill.usage_count, locale) })}
              </span>
            </div>

            {skill.description ? (
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted">
                {skill.description}
              </p>
            ) : null}

            {detail.status === 'failed' ? <ErrorNotice title={t('detailLoadFailed')} /> : null}

            {TEMPLATE_CATEGORIES.has(skill.category) ? (
              <CoreContentSection
                loading={detail.status === 'loading' && !detail.data}
                locked={locked}
                params={detail.data?.params}
              />
            ) : null}

            <HowToUseSection title={skill.title} />

            <div className="flex items-center justify-end gap-3 border-t border-border pt-4">
              <DetailActions
                skill={skill}
                locked={locked}
                isOwner={Boolean(user && skill.author.user_id === user.id)}
                coverUrl={data?.cover_url ?? skill.cover_url ?? null}
                onUnlock={() => requireAuth({ label: skill.title, run: () => setPendingUnlock(true) })}
                onApply={() => requireAuth({ label: skill.title, run: () => void applyAndEnterStudio() })}
                onGoCharacters={() => goLibrary('/create/characters')}
                onGoScenes={() => goLibrary('/create/scenes')}
                onManage={() => setManaging(true)}
                onViewCover={(url) => setViewingCoverUrl(url)}
              />
            </div>
          </div>
        ) : null}
      </Dialog>

      <UnlockDialog
        open={pendingUnlock}
        onClose={() => setPendingUnlock(false)}
        path={skill ? `/v1/skills/${skill.id}/unlock` : ''}
        credits={skill?.access_credits ?? 0}
        title={t('unlock')}
        confirm={t('unlockConfirm', {
          credits: skill?.access_credits ?? 0,
          title: skill?.title ?? '',
        })}
        onUnlocked={() => {
          setPendingUnlock(false);
          setForceUnlocked(true);
          detail.refetch();
          if (skill) onUnlocked(skill.id);
        }}
      />

      {managing && skill ? (
        <ManageSkillDialog
          skill={skill}
          onClose={() => setManaging(false)}
          onChanged={() => setManaging(false)}
        />
      ) : null}

      <MediaLightbox open={viewingCoverUrl !== null} onClose={() => setViewingCoverUrl(null)} src={viewingCoverUrl} />
    </>
  );
}

function CoreContentSection({
  loading,
  locked,
  params,
}: {
  loading: boolean;
  locked: boolean;
  params: Record<string, unknown> | undefined;
}) {
  const t = useTranslations('skillLibrary');

  return (
    <section>
      <h3 className="text-sm font-semibold">{t('coreContentTitle')}</h3>
      <div className="mt-2">
        {loading ? (
          <div className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-4">
            <Spinner label={t('coreContentLoading')} />
          </div>
        ) : locked ? (
          <div className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-dashed border-border bg-surface-soft px-3 py-4 text-xs text-muted">
            <IconLock className="size-4 shrink-0" />
            {t('paramsHidden')}
          </div>
        ) : (
          <CoreContentRows params={params ?? {}} />
        )}
      </div>
    </section>
  );
}

function CoreContentRows({ params }: { params: Record<string, unknown> }) {
  const t = useTranslations('skillLibrary');

  const rows = Object.entries(params)
    .map(([key, value]) => {
      if (value === null || value === undefined || value === '') return null;
      const display = typeof value === 'string' ? value : JSON.stringify(value);
      if (!display) return null;
      const labelKey = PARAM_LABEL_KEY[key];
      return { key, label: labelKey ? t(labelKey) : key, display };
    })
    .filter((row): row is { key: string; label: string; display: string } => row !== null);

  if (rows.length === 0) {
    return (
      <p className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-4 text-xs text-muted">
        {t('coreContentEmpty')}
      </p>
    );
  }

  return (
    <ul className="divide-y divide-border overflow-hidden rounded-[var(--radius-sm)] border border-border">
      {rows.map((row) => (
        <li key={row.key} className="flex items-start gap-3 bg-surface-soft px-3 py-2.5">
          <span className="w-24 shrink-0 pt-0.5 text-xs text-amber">{row.label}</span>
          <span className="min-w-0 flex-1 whitespace-pre-wrap break-words text-xs text-text">
            {row.display}
          </span>
          <CopyIconButton value={row.display} />
        </li>
      ))}
    </ul>
  );
}

function HowToUseSection({ title }: { title: string }) {
  const t = useTranslations('skillLibrary');
  const mention = `@${title} `;

  return (
    <section>
      <h3 className="text-sm font-semibold">{t('howToUseTitle')}</h3>
      <div className="mt-2 flex items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2.5">
        <code className="min-w-0 flex-1 truncate text-xs text-text">{mention}</code>
        <CopyIconButton value={mention} />
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted">{t('howToUseMentionHint')}</p>
    </section>
  );
}

function DetailActions({
  skill,
  locked,
  isOwner,
  coverUrl,
  onUnlock,
  onApply,
  onGoCharacters,
  onGoScenes,
  onManage,
  onViewCover,
}: {
  skill: CreationSkillSummary;
  locked: boolean;
  isOwner: boolean;
  coverUrl: string | null;
  onUnlock: () => void;
  onApply: () => void;
  onGoCharacters: () => void;
  onGoScenes: () => void;
  onManage: () => void;
  onViewCover: (url: string | null) => void;
}) {
  const t = useTranslations('skillLibrary');

  if (TEMPLATE_CATEGORIES.has(skill.category)) {
    return locked ? (
      <Button onClick={onUnlock}>{t('unlock')}</Button>
    ) : (
      <Button onClick={onApply}>{t('goCreate')}</Button>
    );
  }
  if (skill.category === 'character') {
    return <Button onClick={onGoCharacters}>{t('goCharacterLibrary')}</Button>;
  }
  if (skill.category === 'scene_asset') {
    return <Button onClick={onGoScenes}>{t('goSceneLibrary')}</Button>;
  }
  // cover_asset
  if (isOwner) return <Button onClick={onManage}>{t('manage')}</Button>;
  if (locked) return <Button onClick={onUnlock}>{t('unlock')}</Button>;
  return <Button onClick={() => onViewCover(coverUrl)}>{t('viewCoverImage')}</Button>;
}

function CopyIconButton({ value }: { value: string }) {
  const tActions = useTranslations('actions');
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      aria-label={copied ? tActions('copied') : tActions('copy')}
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        });
      }}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-[var(--radius-sm)] p-1.5 text-muted transition-colors hover:text-text',
      )}
    >
      {copied ? <IconCheck className="size-3.5 text-success" /> : <IconCopy className="size-3.5" />}
    </button>
  );
}

