'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useId, useMemo, useReducer, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { AGE_STAGES, SCENE_LIGHTINGS, SCENE_PERIODS } from '@/features/image-assets/vocabulary';
import type { Locale } from '@/i18n/routing';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type {
  Character,
  Prop,
  QualityTier,
  Scene,
  ScriptBreakdown,
  ScriptBreakdownApplyResponse,
} from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatCount } from '@/lib/format';
import { useResource } from '@/lib/use-resource';

import {
  applyItems,
  BREAKDOWN_KINDS,
  breakdownReducer,
  createBlocked,
  createCounts,
  EMPTY_BREAKDOWN,
  incompleteRows,
  nothingToApply,
  quoteLines,
  rowsOf,
  type BreakdownAction,
  type BreakdownKind,
  type BreakdownRow,
} from './asset-breakdown-model';

const TIERS: QualityTier[] = ['preview', 'standard', 'cinematic'];
const ACTIONS: BreakdownAction[] = ['create', 'link', 'skip'];

interface BatchQuoteResult {
  total_credits: number;
  available_credits: number;
  period_remaining: number | null;
  within_spend_limit: boolean;
  sufficient: boolean;
}

/** One quote fetch's inputs; its identity marks a settled result as current. */
interface QuoteRequest {
  lines: ReturnType<typeof quoteLines>;
}

const LIBRARY_PATH: Record<BreakdownKind, string> = {
  character: '/v1/characters',
  scene: '/v1/scenes',
  prop: '/v1/props',
};

/** 新建 / 关联已有 / 忽略 for one row — a radio group, so arrow keys move
 * between the three and the choice is announced. */
function ActionSwitch({
  label,
  value,
  createDisabled,
  onChange,
}: {
  label: string;
  value: BreakdownAction;
  createDisabled: boolean;
  onChange: (action: BreakdownAction) => void;
}) {
  const t = useTranslations('assetBreakdown');
  const name = useId();
  return (
    <div role="radiogroup" aria-label={label} className="grid grid-cols-3 gap-1">
      {ACTIONS.map((action) => {
        const disabled = action === 'create' && createDisabled;
        const selected = action === value;
        return (
          <label
            key={action}
            className={cn(
              'cursor-pointer rounded-[var(--radius-sm)] border px-2 py-1 text-center text-xs transition-colors',
              'focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--focus)]',
              selected
                ? 'border-primary bg-primary/10 text-text'
                : 'border-border text-muted hover:border-border-strong hover:text-text',
              disabled && 'cursor-not-allowed opacity-50 hover:border-border hover:text-muted',
            )}
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              checked={selected}
              disabled={disabled}
              onChange={() => onChange(action)}
            />
            {t(`action.${action}`)}
          </label>
        );
      })}
    </div>
  );
}

function RowCard({
  row,
  cards,
  onAction,
  onCard,
}: {
  row: BreakdownRow;
  cards: { id: string; name: string }[];
  onAction: (action: BreakdownAction) => void;
  onCard: (cardId: string | null) => void;
}) {
  const t = useTranslations('assetBreakdown');
  const tVariants = useTranslations('assetVariants');
  const tPresets = useTranslations('remixPage');
  const { item } = row;
  const blocked = createBlocked(item);
  const matchIds = new Set((item.matches ?? []).map((match) => match.id));
  const presets = [
    item.age_stage ? tVariants(AGE_STAGES[item.age_stage].labelKey) : null,
    item.period ? tPresets(`presets.${SCENE_PERIODS[item.period].labelKey}`) : null,
    item.lighting ? tPresets(`presets.${SCENE_LIGHTINGS[item.lighting].labelKey}`) : null,
  ].filter(Boolean);
  const headings = item.headings ?? [];

  return (
    <li
      className={cn(
        'flex min-w-0 flex-col gap-2 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-3',
        row.action === 'skip' && 'opacity-70',
      )}
    >
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
        <p className="min-w-0 break-words text-sm font-medium">{item.name}</p>
        {presets.length ? <p className="text-[11px] text-muted">{presets.join(' · ')}</p> : null}
      </div>
      {item.description ? (
        <p className="line-clamp-3 break-words text-xs text-muted">{item.description}</p>
      ) : null}
      {headings.length ? (
        <p className="break-words text-[11px] text-muted">
          {t(item.kind === 'scene' ? 'headings' : 'appearsIn', { list: headings.join('、') })}
        </p>
      ) : null}
      <ActionSwitch
        label={t('actionLabel', { name: item.name })}
        value={row.action}
        createDisabled={blocked}
        onChange={onAction}
      />
      {blocked ? <p className="text-[11px] text-muted">{t('nameTaken')}</p> : null}
      {row.action === 'link' ? (
        <Select
          label={t('linkTo')}
          value={row.cardId ?? ''}
          error={row.cardId ? undefined : t('linkRequired')}
          onChange={(event) => onCard(event.target.value || null)}
          options={[
            { value: '', label: t('linkPlaceholder') },
            ...[...cards]
              .sort((a, b) => Number(matchIds.has(b.id)) - Number(matchIds.has(a.id)))
              .map((card) => ({
                value: card.id,
                label: matchIds.has(card.id) ? t('sameName', { name: card.name }) : card.name,
              })),
          ]}
        />
      ) : null}
    </li>
  );
}

/**
 * 剧本拆解建卡 (AC-9): AI proposes the script's characters, places and props
 * (`POST /v1/scripts/{id}:breakdown`); per row the author picks 新建 / 关联已有
 * / 忽略, optionally with a first image for every new card (quoted live
 * through `quote:batch`), then one `…:breakdown-apply` creates the cards and
 * writes the links. Mount only while open — each opening re-runs the
 * breakdown. `kinds` limits the columns (a library page imports its own
 * kind); rows of other kinds are left alone.
 */
export function AssetBreakdownDialog({
  episodeId,
  kinds = BREAKDOWN_KINDS,
  onClose,
  onApplied,
}: {
  episodeId: string;
  kinds?: readonly BreakdownKind[];
  onClose: () => void;
  onApplied?: (result: ScriptBreakdownApplyResponse) => void;
}) {
  const t = useTranslations('assetBreakdown');
  const tScript = useTranslations('scriptStudio');
  const tCredits = useTranslations('credits');
  const locale = useLocale() as Locale;
  const { notify } = useToast();

  const [state, dispatch] = useReducer(breakdownReducer, EMPTY_BREAKDOWN);
  const [attempt, setAttempt] = useState(0);
  // The settled breakdown fetch, tagged with the attempt it answered.
  const [fetched, setFetched] = useState<{
    attempt: number;
    breakdown: ScriptBreakdown | null;
    error: string | null;
  } | null>(null);
  const [generate, setGenerate] = useState(true);
  const [tier, setTier] = useState<QualityTier>('standard');
  const [quoteResult, setQuoteResult] = useState<{
    request: QuoteRequest;
    quote: BatchQuoteResult | null;
  } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const pendingKey = useRef<string | null>(null);

  const kindsKey = kinds.join(',');
  useEffect(() => {
    let cancelled = false;
    void api
      .post<ScriptBreakdown>(`/v1/scripts/${episodeId}:breakdown`)
      .then((breakdown) => {
        if (cancelled) return;
        setFetched({ attempt, breakdown, error: null });
        dispatch({ type: 'load', breakdown, kinds: kindsKey.split(',') as BreakdownKind[] });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setFetched({
          attempt,
          breakdown: null,
          error: isApiError(error) ? error.message : t('analyzeFailed'),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [episodeId, attempt, kindsKey, t]);

  const analyzing = fetched?.attempt !== attempt;
  const breakdown = analyzing ? null : (fetched?.breakdown ?? null);
  const analyzeError = analyzing ? null : (fetched?.error ?? null);

  const characters = useResource<Character[]>(
    kinds.includes('character') ? LIBRARY_PATH.character : null,
  );
  const scenes = useResource<Scene[]>(kinds.includes('scene') ? LIBRARY_PATH.scene : null);
  const props = useResource<Prop[]>(kinds.includes('prop') ? LIBRARY_PATH.prop : null);
  const cardsByKind: Record<BreakdownKind, { id: string; name: string }[]> = {
    character: characters.data ?? [],
    scene: scenes.data ?? [],
    prop: props.data ?? [],
  };

  // Keyed on the numbers, not the `counts` object rebuilt every render.
  const { character: newCharacters, scene: newScenes, prop: newProps } = createCounts(state);
  const imageCount = generate ? newCharacters + newScenes + newProps : 0;
  const quoteRequest = useMemo<QuoteRequest | null>(
    () =>
      imageCount > 0
        ? {
            lines: quoteLines({ character: newCharacters, scene: newScenes, prop: newProps }, tier),
          }
        : null,
    [imageCount, newCharacters, newScenes, newProps, tier],
  );
  const quoting = quoteRequest !== null && quoteResult?.request !== quoteRequest;
  const quote = quoteRequest && !quoting ? (quoteResult?.quote ?? null) : null;
  const quoteFailed = quoteRequest !== null && !quoting && quote === null;

  useEffect(() => {
    if (!quoteRequest) return;
    let cancelled = false;
    void api
      .post<BatchQuoteResult>('/v1/generation-jobs/quote:batch', { items: quoteRequest.lines })
      .then((next) => {
        if (!cancelled) setQuoteResult({ request: quoteRequest, quote: next });
      })
      .catch(() => {
        if (!cancelled) setQuoteResult({ request: quoteRequest, quote: null });
      });
    return () => {
      cancelled = true;
    };
  }, [quoteRequest]);

  const incomplete = incompleteRows(state).length;
  const canSubmit =
    Boolean(breakdown) &&
    !submitting &&
    !nothingToApply(state) &&
    incomplete === 0 &&
    (imageCount === 0 || Boolean(quote?.sufficient));

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    pendingKey.current ??= newIdempotencyKey();
    try {
      const result = await api.post<ScriptBreakdownApplyResponse>(
        `/v1/scripts/${episodeId}:breakdown-apply`,
        {
          items: applyItems(state),
          generate: { enabled: imageCount > 0, quality_tier: tier },
          dry_run: false,
        },
        { idempotencyKey: pendingKey.current },
      );
      pendingKey.current = null;
      const created = result.items.filter((item) => item.created).length;
      const linked = result.items.filter((item) => item.action === 'link').length;
      const failed = result.items.filter((item) => item.error);
      notify(
        [
          t('applied', { created, linked }),
          result.submitted ? t('appliedJobs', { count: result.submitted }) : null,
          failed.length
            ? t('appliedErrors', { count: failed.length, message: failed[0]?.error ?? '' })
            : null,
        ]
          .filter(Boolean)
          .join(' '),
        failed.length ? 'error' : 'success',
      );
      onApplied?.(result);
      onClose();
    } catch (error) {
      if (isApiError(error) && error.code === 'IDEMPOTENCY_CONFLICT') pendingKey.current = null;
      setSubmitError(isApiError(error) ? error.message : t('applyFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  const columnTitle: Record<BreakdownKind, string> = {
    character: t('columnCharacters'),
    scene: t('columnScenes'),
    prop: t('columnProps'),
  };

  return (
    <Dialog
      open
      onClose={submitting ? () => undefined : onClose}
      title={t('title')}
      description={t('description')}
      size="xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            {t('cancel')}
          </Button>
          <Button disabled={!canSubmit} loading={submitting} onClick={() => void submit()}>
            {t('submit')}
          </Button>
        </>
      }
    >
      {analyzing ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted" role="status">
          <Spinner />
          {t('analyzing')}
        </div>
      ) : analyzeError || !breakdown ? (
        <ErrorNotice
          title={analyzeError ?? t('analyzeFailed')}
          action={
            <Button size="sm" variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
              {t('retry')}
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-4">
          {breakdown.degraded ? <p className="text-xs text-amber">{t('degraded')}</p> : null}
          <div
            className={cn(
              'grid gap-4',
              kinds.length === 3 && 'lg:grid-cols-3',
              kinds.length === 2 && 'md:grid-cols-2',
            )}
          >
            {kinds.map((kind) => {
              const rows = rowsOf(state, kind);
              const createCount = rows.filter((row) => row.action === 'create').length;
              const linkCount = rows.filter((row) => row.action === 'link').length;
              return (
                <section key={kind} className="flex min-w-0 flex-col gap-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold">
                      {columnTitle[kind]}
                      <span className="ml-2 text-xs font-normal text-muted">
                        {t('columnSummary', { create: createCount, link: linkCount })}
                      </span>
                    </h3>
                    {rows.length ? (
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => dispatch({ type: 'column', kind, action: 'create' })}
                        >
                          {t('createAll')}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => dispatch({ type: 'column', kind, action: 'skip' })}
                        >
                          {t('skipAll')}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                  {rows.length ? (
                    <ul className="flex flex-col gap-2 lg:max-h-[50vh] lg:overflow-y-auto">
                      {rows.map((row) => (
                        <RowCard
                          key={row.key}
                          row={row}
                          cards={cardsByKind[kind]}
                          onAction={(action) => dispatch({ type: 'action', key: row.key, action })}
                          onCard={(cardId) => dispatch({ type: 'card', key: row.key, cardId })}
                        />
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted">{t('columnEmpty')}</p>
                  )}
                </section>
              );
            })}
          </div>

          <div className="flex flex-col gap-3 rounded-[var(--radius-sm)] border border-border p-3">
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={generate}
                onChange={(event) => setGenerate(event.target.checked)}
                className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
              />
              <span className="flex flex-col gap-0.5">
                {t('generateLabel')}
                <span className="text-xs text-muted">{t('generateHint')}</span>
              </span>
            </label>
            {generate ? (
              <Select
                label={tScript('batchQuality')}
                value={tier}
                options={TIERS.map((value) => ({ value, label: tScript(`batchTier.${value}`) }))}
                onChange={(event) => setTier(event.target.value as QualityTier)}
              />
            ) : null}
            {imageCount > 0 && quoting ? (
              <p className="flex items-center gap-2 text-xs text-muted" role="status">
                <Spinner />
                {t('quoting')}
              </p>
            ) : null}
            {imageCount > 0 && quote ? (
              <p className="text-sm text-amber">
                {t('total', {
                  count: imageCount,
                  credits: tCredits('amount', {
                    count: formatCount(quote.total_credits, locale),
                  }),
                })}
              </p>
            ) : null}
            {quoteFailed ? <ErrorNotice title={t('quoteFailed')} /> : null}
            {quote && !quote.sufficient ? (
              <ErrorNotice
                title={
                  quote.within_spend_limit
                    ? t('insufficient')
                    : t('spendLimit', {
                        remaining: formatCount(quote.period_remaining ?? 0, locale),
                      })
                }
              />
            ) : null}
          </div>

          {incomplete > 0 ? (
            <p className="text-xs text-muted">{t('incomplete', { count: incomplete })}</p>
          ) : null}
          {nothingToApply(state) ? (
            <p className="text-xs text-muted">{t('nothingToApply')}</p>
          ) : null}
          {submitError ? <ErrorNotice title={submitError} /> : null}
        </div>
      )}
    </Dialog>
  );
}
