'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import type { CardKind } from '@/components/library/entry-actions';
import { ChipGroup } from '@/features/image-assets/chip-group';
import { Button } from '@/components/ui/button';
import { Select, TextArea } from '@/components/ui/field';
import { Badge, ErrorNotice } from '@/components/ui/primitives';
import {
  CHARACTER_EXPRESSIONS,
  type CharacterExpression,
  keysOf,
  MAX_CHARACTER_EXPRESSIONS,
} from '@/features/image-assets/vocabulary';
import { DEFAULT_FILL_EXPRESSIONS } from '@/features/image-assets/fill';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type {
  AssetEntry,
  AssetGenerateResponse,
  AssetGraph,
  AssetVariant,
  CameraPose,
  CreationSkillSummary,
  Page,
  Quote,
} from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { isSkillMentionable } from '@/lib/skill-mention';
import { useResource } from '@/lib/use-resource';

import type { AssetGraphActions } from '@/components/asset-graph/use-asset-graph';

import { poseKey } from './camera';
import { orbitSource, type SlotState } from './completeness';
import { cardBase } from './kind-config';
import { type Coverage, OrbitPicker } from './orbit-picker';
import { PanoramaDialog } from './panorama-dialog';
import { slotJob } from './slot-jobs';

const QUOTE_DEBOUNCE_MS = 300;
const TIERS = ['preview', 'standard', 'cinematic'] as const;
type Tier = (typeof TIERS)[number];
const MAX_CANDIDATES = 4;
/** Template categories that read as a look, not a recipe for an asset. */
const STYLE_CATEGORIES = new Set(['style', 'lens', 'scene', 'other']);

interface Priced {
  key: string;
  credits: number;
  available: number;
  sufficient: boolean;
}

/**
 * The generation panel for the selected slot of the 创作 board:
 *
 * - a pose slot — the 角度盘, drawing the chosen camera poses from the look's
 *   front figure / sheet (character) or master (scene, prop) via `…:orbit`;
 * - the in-scene slot — a 派生 `in_scene` from the sheet (`…:derive`);
 * - the panorama slot (scene, AC-7) — a 2:1 panorama job like the slots
 *   below, plus the viewer that cuts posed shots out of it;
 * - every other slot — a draftless job filing into the card, 1–4 candidates,
 *   with an optional style skill.
 *
 * Each submit holds one idempotency key until it succeeds (a double click or
 * a retry never queues twice); candidate `i` uses `{key}:{i}`.
 */
export function SlotPanel({
  kind,
  graph,
  variant,
  state,
  states,
  actions,
  initialSkillId,
  onSubmitted,
  onFill,
}: {
  kind: CardKind;
  graph: AssetGraph;
  variant: AssetVariant;
  state: SlotState;
  states: SlotState[];
  actions: AssetGraphActions;
  /** A plaza style skill carried in by `?skillId=` (AC-8): preselected. */
  initialSkillId?: string | null;
  onSubmitted: () => void;
  /** Character looks: open 补齐缺失. */
  onFill?: () => void;
}) {
  const t = useTranslations('assetWorkspace');
  const tPresets = useTranslations('remixPage');
  const slot = state.slot;
  const base = cardBase(kind, graph.card_id);
  const [tier, setTier] = useState<Tier>('standard');
  const [extra, setExtra] = useState('');
  const [count, setCount] = useState(1);
  const [skillId, setSkillId] = useState(initialSkillId ?? '');
  const [expressions, setExpressions] = useState<CharacterExpression[]>([
    ...DEFAULT_FILL_EXPRESSIONS,
  ]);
  const missingPoses = useMemo(
    () =>
      states
        .filter((s) => s.slot.kind === 'pose' && s.slot.required && s.status === 'missing')
        .map((s) => s.slot.pose as CameraPose),
    [states],
  );
  const [poses, setPoses] = useState<CameraPose[]>(() =>
    slot.pose ? [slot.pose, ...missingPoses.filter((p) => poseKey(p) !== poseKey(slot.pose!))] : [],
  );
  const [priced, setPriced] = useState<Priced | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [viewing, setViewing] = useState(false);
  const idempotencyKey = useRef<string | null>(null);
  const panorama =
    slot.kind === 'panorama' ? (state.approved ?? state.candidates[0] ?? null) : null;

  const source = orbitSource(kind, variant);
  const sheet = (variant.entries ?? []).find(
    (e) => e.status === 'approved' && e.entry_type === 'character_sheet',
  );
  const coverage: Coverage = useMemo(() => {
    const map: Coverage = new Map();
    for (const s of states) {
      if (s.slot.kind !== 'pose' || !s.slot.pose) continue;
      if (s.status === 'approved') map.set(poseKey(s.slot.pose), 'approved');
      else if (s.status === 'candidate') map.set(poseKey(s.slot.pose), 'candidate');
    }
    return map;
  }, [states]);

  const skills = useResource<Page<CreationSkillSummary>>(
    '/v1/skills/public?content_type=template&limit=60',
  );
  // The carried skill may be any image template (the plaza sends every
  // image-only recipe here), or beyond the first page — fetch it on its own.
  const carried = useResource<CreationSkillSummary>(
    initialSkillId ? `/v1/skills/${encodeURIComponent(initialSkillId)}` : null,
  );
  const listed = (skills.data?.items ?? []).filter(
    (skill) => STYLE_CATEGORIES.has(skill.category) && isSkillMentionable(skill, 'text_to_image'),
  );
  const styleSkills =
    carried.data && !listed.some((skill) => skill.id === carried.data?.id)
      ? [carried.data, ...listed]
      : listed;

  // What a submit would send, and the request that prices it.
  const plan = useMemo((): {
    url: string;
    body: Record<string, unknown>;
    kind: 'job' | 'orbit' | 'derive';
  } | null => {
    if (slot.kind === 'pose') {
      if (!source || !poses.length) return null;
      return {
        url: `${base}/entries/${source.id}:orbit`,
        body: { poses, quality_tier: tier },
        kind: 'orbit',
      };
    }
    if (slot.kind === 'in_scene') {
      if (!sheet || !variant.scene_link) return null;
      return {
        url: `${base}/entries/${sheet.id}:derive`,
        body: {
          output: 'in_scene',
          target_variant_id: variant.id,
          prompt_extra: extra.trim() || null,
          quality_tier: tier,
        },
        kind: 'derive',
      };
    }
    const job = slotJob(kind, graph, variant, slot, {
      extra,
      expressions,
      skillId: skillId || null,
    });
    if (!job) return null;
    return {
      url: '/v1/generation-jobs',
      body: { operation: job.operation, quality_tier: tier, params: job.params },
      kind: 'job',
    };
  }, [slot, source, sheet, poses, base, tier, extra, expressions, skillId, kind, graph, variant]);
  const planKey = plan ? JSON.stringify(plan) : '';

  useEffect(() => {
    if (!plan) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const request: Promise<Priced> =
        plan.kind === 'job'
          ? api
              .post<Quote>('/v1/generation-jobs/quote', {
                operation: 'text_to_image',
                quality_tier: tier,
                asset_kind: (plan.body.params as Record<string, unknown>).asset_kind,
              })
              .then((quote) => ({
                key: planKey,
                credits: quote.credits * count,
                available: quote.available_credits,
                sufficient: quote.available_credits >= quote.credits * count,
              }))
          : api
              .post<AssetGenerateResponse>(plan.url, { ...plan.body, dry_run: true })
              .then((response) => ({
                key: planKey,
                credits: response.credits,
                available: response.available_credits,
                sufficient: response.sufficient,
              }));
      request
        .then((next) => {
          if (!cancelled) {
            setPriced(next);
            setError(null);
          }
        })
        .catch((caught: unknown) => {
          if (!cancelled) setError(caught instanceof ApiError ? caught.message : t('genericError'));
        });
    }, QUOTE_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // `plan` is captured through `planKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planKey, count, tier, t]);

  const submit = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    idempotencyKey.current ??= newIdempotencyKey();
    const key = idempotencyKey.current;
    try {
      if (plan.kind === 'job') {
        for (let index = 0; index < count; index += 1) {
          await api.post(plan.url, plan.body, { idempotencyKey: `${key}:${index}` });
        }
      } else {
        await api.post(plan.url, { ...plan.body, dry_run: false }, { idempotencyKey: key });
      }
      idempotencyKey.current = null;
      onSubmitted();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('genericError'));
    } finally {
      setBusy(false);
    }
  };

  const current = priced?.key === planKey ? priced : null;
  const blocked =
    slot.kind === 'pose' && !source
      ? t(kind === 'character' ? 'needSheet' : 'needMaster')
      : slot.kind === 'in_scene' && !sheet
        ? t('needSheet')
        : slot.kind === 'in_scene' && !variant.scene_link
          ? t('needSceneLink')
          : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t(`slot.${slot.id}`)}</h3>
        <Badge tone={state.status === 'approved' ? 'success' : 'neutral'}>
          {t(`status.${state.status}`)}
        </Badge>
      </div>

      <SlotImages
        approved={state.approved}
        candidates={state.candidates}
        wide={slot.kind === 'panorama'}
        onApprove={(entry) => void actions.approveEntry(entry.id)}
      />

      {slot.kind === 'panorama' ? (
        <>
          <p className="text-xs text-muted">{t('panorama.slotHint')}</p>
          {panorama ? (
            <Button variant="secondary" onClick={() => setViewing(true)}>
              {t('panorama.open')}
            </Button>
          ) : null}
          {panorama && viewing ? (
            <PanoramaDialog
              open
              onClose={() => setViewing(false)}
              panorama={panorama}
              variant={variant}
              actions={actions}
            />
          ) : null}
        </>
      ) : null}

      {blocked ? (
        <p className="rounded-[var(--radius-sm)] bg-surface-soft p-3 text-sm text-muted">
          {blocked}
        </p>
      ) : (
        <>
          {slot.kind === 'pose' ? (
            <>
              <p className="text-xs text-muted">
                {t('orbitSource', {
                  source: t(
                    source?.entry_type === 'character_sheet' ? 'sourceSheet' : 'sourceImage',
                  ),
                })}
              </p>
              <OrbitPicker selected={poses} onChange={setPoses} coverage={coverage} />
            </>
          ) : null}

          {slot.kind === 'expressions' ? (
            <ChipGroup
              label={t('expressionsLabel')}
              options={keysOf(CHARACTER_EXPRESSIONS).map((key) => ({
                value: key,
                label: tPresets(`presets.${CHARACTER_EXPRESSIONS[key].labelKey}`),
              }))}
              selected={expressions}
              max={MAX_CHARACTER_EXPRESSIONS}
              onToggle={(value) =>
                setExpressions((list) =>
                  list.includes(value)
                    ? list.length > 1
                      ? list.filter((item) => item !== value)
                      : list
                    : [...list, value],
                )
              }
            />
          ) : null}

          {slot.kind !== 'pose' ? (
            <TextArea
              label={t('extraLabel')}
              hint={t('extraHint')}
              value={extra}
              maxLength={500}
              rows={3}
              onChange={(event) => setExtra(event.target.value)}
            />
          ) : null}

          {plan?.kind === 'job' ? (
            <>
              <Select
                label={t('styleSkill')}
                hint={t('styleSkillHint')}
                value={skillId}
                onChange={(event) => setSkillId(event.target.value)}
                options={[
                  { value: '', label: t('styleSkillNone') },
                  ...styleSkills.map((skill) => ({ value: skill.id, label: skill.title })),
                ]}
              />
              <Select
                label={t('candidates')}
                value={String(count)}
                onChange={(event) => setCount(Number(event.target.value))}
                options={Array.from({ length: MAX_CANDIDATES }, (_, i) => ({
                  value: String(i + 1),
                  label: t('candidateCount', { count: i + 1 }),
                }))}
              />
            </>
          ) : null}

          <Select
            label={t('quality')}
            value={tier}
            onChange={(event) => setTier(event.target.value as Tier)}
            options={TIERS.map((value) => ({ value, label: t(`tier.${value}`) }))}
          />

          {error ? <ErrorNotice title={error} /> : null}

          <div className="flex flex-col gap-2">
            <Button
              loading={busy}
              disabled={!plan || !current || !current.sufficient}
              onClick={() => void submit()}
            >
              {current ? t('generateFor', { credits: current.credits }) : t('generatePricing')}
            </Button>
            {current && !current.sufficient ? (
              <p className="text-xs text-danger">
                {t('insufficient', { available: current.available })}
              </p>
            ) : null}
            {onFill ? (
              <Button variant="secondary" onClick={onFill}>
                {t('fillAll')}
              </Button>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}

function SlotImages({
  approved,
  candidates,
  wide = false,
  onApprove,
}: {
  approved: AssetEntry | null;
  candidates: AssetEntry[];
  /** A 2:1 panorama: shown whole rather than cropped. */
  wide?: boolean;
  onApprove: (entry: AssetEntry) => void;
}) {
  const t = useTranslations('assetWorkspace');
  if (!approved && !candidates.length) return null;
  return (
    <div className="flex flex-col gap-2">
      {approved?.url ? (
        <div
          className={cn(
            'relative overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft',
            wide ? 'aspect-[2/1]' : 'aspect-video',
          )}
        >
          <Image src={approved.url} alt="" fill sizes="360px" className="object-contain" />
        </div>
      ) : null}
      {candidates.length ? (
        <>
          <p className="text-xs text-muted">{t('candidatesHint', { count: candidates.length })}</p>
          <ul className="grid grid-cols-3 gap-2">
            {candidates.map((entry) => (
              <li key={entry.id} className="flex flex-col gap-1">
                <div
                  className={cn(
                    'relative overflow-hidden rounded-[var(--radius-sm)] border border-dashed border-border bg-surface-soft',
                    wide ? 'aspect-[2/1]' : 'aspect-square',
                  )}
                >
                  {entry.url ? (
                    <Image
                      src={entry.url}
                      alt=""
                      fill
                      sizes="120px"
                      className={wide ? 'object-contain' : 'object-cover'}
                    />
                  ) : null}
                </div>
                <Button size="sm" variant="secondary" onClick={() => onApprove(entry)}>
                  {t('approve')}
                </Button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
