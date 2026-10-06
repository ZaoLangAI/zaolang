'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import type { CardKind } from '@/components/library/entry-actions';
import { PropPresetFields, propPresetsOf } from '@/components/library/prop-preset-fields';
import { ScenePresetFields } from '@/components/library/scene-preset-fields';
import { LOOK_ATTRIBUTE_LIMITS } from '@/components/library/variant-attributes-form';
import { Button } from '@/components/ui/button';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { IconSparkle } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import {
  AGE_STAGES,
  keysOf,
  type PropPresets,
  SCENE_PERIODS,
  type ScenePresets,
} from '@/features/image-assets/vocabulary';
import { cardBase } from '@/features/asset-workspace/kind-config';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type {
  AssetEntry,
  AssetGenerateResponse,
  AssetGraph,
  AssetRelation,
  AssetVariant,
} from '@/lib/api/types';
import { cn } from '@/lib/cn';

import { RELATION_COLOR, relationLabelKey } from '../relations';

type Mode = 'adjust' | 'derive';
type CharacterOutput = 'character_sheet' | 'identity_portrait' | 'expression_sheet' | 'in_scene';
type SceneOutput = 'master' | 'shot';

const CHARACTER_OUTPUTS: CharacterOutput[] = [
  'character_sheet',
  'identity_portrait',
  'expression_sheet',
  'in_scene',
];
const SCENE_OUTPUTS: SceneOutput[] = ['master', 'shot'];
const QUOTE_DEBOUNCE_MS = 300;

interface LookDraft {
  name: string;
  description: string;
  ageStage: string;
  period: string;
  outfit: string;
  state: string;
  scenePresets: ScenePresets;
  propPresets: PropPresets;
}

function draftFrom(look: AssetVariant): LookDraft {
  const presets = (look.presets ?? {}) as ScenePresets & { age_stage?: string | null };
  return {
    name: '',
    description: look.is_default ? '' : (look.description ?? ''),
    ageStage: presets.age_stage ?? '',
    period: presets.period ?? '',
    outfit: look.attributes?.outfit ?? '',
    state: look.attributes?.state ?? '',
    scenePresets: { ...presets },
    propPresets: propPresetsOf(look.presets),
  };
}

/**
 * Generating from the selected image without leaving the page (P6):
 *
 * - 调整修改: a new *version* of this image, changing only what the
 *   instruction says — filed as a candidate beside it, folded into the same
 *   graph node (`versions.ts`), chosen with 定稿 in the version list.
 * - 派生新属性图: an image for another look — a new one drafted from this
 *   look's attributes (the changed ones become the relation), or an
 *   existing one — drawn from this image.
 *
 * Quotes with a debounced dry run; a submit reuses one idempotency key until
 * it succeeds, so a double click or a retry never queues two jobs.
 */
export function GeneratePanel({
  graph,
  kind,
  entry,
  variant,
  onSubmitted,
}: {
  graph: AssetGraph;
  kind: CardKind;
  entry: AssetEntry;
  variant: AssetVariant;
  onSubmitted: (response: AssetGenerateResponse) => void;
}) {
  const t = useTranslations('assetGraph');
  const tVariants = useTranslations('assetVariants');
  const tPresets = useTranslations('remixPage');
  const { notify } = useToast();
  const character = kind === 'character';
  const base = `${cardBase(kind, graph.card_id)}/entries/${entry.id}`;
  const [mode, setMode] = useState<Mode>('adjust');
  const [instruction, setInstruction] = useState('');
  const [targetMode, setTargetMode] = useState<'new' | 'existing'>('new');
  const [targetId, setTargetId] = useState('');
  const [output, setOutput] = useState<string>(character ? 'character_sheet' : 'master');
  const [extra, setExtra] = useState('');
  const [draft, setDraft] = useState<LookDraft>(() => draftFrom(variant));
  const [quote, setQuote] = useState<{ key: string; response: AssetGenerateResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  const others = (graph.variants ?? []).filter((v) => v.id !== variant.id);
  const body =
    mode === 'adjust'
      ? { url: `${base}:adjust`, payload: { instruction: instruction.trim() } }
      : {
          url: `${base}:derive`,
          payload: {
            output,
            prompt_extra: extra.trim() || null,
            ...(targetMode === 'existing'
              ? { target_variant_id: targetId || null }
              : {
                  new_variant: {
                    name: draft.name.trim(),
                    description: draft.description.trim() || null,
                    presets: character
                      ? { age_stage: draft.ageStage || null, period: draft.period || null }
                      : kind === 'prop'
                        ? draft.propPresets
                        : draft.scenePresets,
                    attributes: character
                      ? { outfit: draft.outfit.trim() || null, state: draft.state.trim() || null }
                      : null,
                    ...(variant.scene_link
                      ? {
                          scene_id: variant.scene_link.scene_id,
                          scene_variant_id: variant.scene_link.variant_id ?? null,
                        }
                      : {}),
                  },
                }),
          },
        };
  const ready =
    mode === 'adjust'
      ? instruction.trim().length > 0
      : targetMode === 'existing'
        ? Boolean(targetId)
        : draft.name.trim().length > 0;
  const bodyKey = JSON.stringify(body);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const { url, payload } = JSON.parse(bodyKey) as typeof body;
      api
        .post<AssetGenerateResponse>(url, { ...payload, dry_run: true })
        .then((response) => {
          if (cancelled) return;
          setQuote({ key: bodyKey, response });
          setError(null);
        })
        .catch((caught: unknown) => {
          if (!cancelled) setError(caught instanceof ApiError ? caught.message : t('genericError'));
        });
    }, QUOTE_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // `body` is fully captured by `bodyKey`.
  }, [bodyKey, ready, t]);

  const current = quote?.key === bodyKey ? quote.response : null;

  const submit = async () => {
    setBusy(true);
    setError(null);
    idempotencyKey.current ??= newIdempotencyKey();
    try {
      const response = await api.post<AssetGenerateResponse>(
        body.url,
        { ...body.payload, dry_run: false },
        { idempotencyKey: idempotencyKey.current },
      );
      idempotencyKey.current = null;
      notify(mode === 'adjust' ? t('adjustQueued') : t('deriveQueued'), 'success');
      setInstruction('');
      setExtra('');
      setDraft(draftFrom(variant));
      onSubmitted(response);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('genericError'));
    } finally {
      setBusy(false);
    }
  };

  const tab = (value: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === value}
      onClick={() => setMode(value)}
      className={cn(
        'flex-1 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs transition-colors focus-visible:outline-2',
        mode === value ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-text',
      )}
    >
      {label}
    </button>
  );

  return (
    <div className="flex flex-col gap-3">
      <div role="tablist" className="flex gap-1 rounded-[var(--radius-sm)] bg-surface-soft p-1">
        {tab('adjust', t('modeAdjust'))}
        {tab('derive', t('modeDerive'))}
      </div>

      {mode === 'adjust' ? (
        <TextArea
          label={t('adjustInstruction')}
          hint={t('adjustHint')}
          value={instruction}
          maxLength={500}
          className="min-h-20"
          onChange={(event) => setInstruction(event.target.value)}
        />
      ) : (
        <>
          <Select
            label={t('deriveOutput')}
            value={output}
            onChange={(event) => setOutput(event.target.value)}
            options={(character ? CHARACTER_OUTPUTS : SCENE_OUTPUTS).map((value) => ({
              value,
              label: t(`output.${kind === 'prop' ? `prop_${value}` : value}`),
            }))}
          />
          <div role="radiogroup" aria-label={t('deriveTarget')} className="flex gap-4 text-sm">
            {(['new', 'existing'] as const).map((value) => (
              <label key={value} className="flex cursor-pointer items-center gap-1.5">
                <input
                  type="radio"
                  name={`derive-target-${entry.id}`}
                  checked={targetMode === value}
                  disabled={value === 'existing' && others.length === 0}
                  onChange={() => setTargetMode(value)}
                  className="accent-[var(--primary)]"
                />
                {value === 'new' ? t('deriveTargetNew') : t('deriveTargetExisting')}
              </label>
            ))}
          </div>
          {targetMode === 'existing' ? (
            <Select
              label={t('deriveTargetLook')}
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              options={[
                { value: '', label: t('pickNode') },
                ...others.map((v) => ({ value: v.id, label: v.name })),
              ]}
            />
          ) : (
            <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-dashed border-border p-3">
              <p className="text-xs text-muted">{t('deriveDraftHint', { name: variant.name })}</p>
              <TextInput
                label={tVariants('name')}
                value={draft.name}
                maxLength={40}
                placeholder={tVariants(
                  character
                    ? 'lookPlaceholder'
                    : kind === 'prop'
                      ? 'propVariantPlaceholder'
                      : 'variantPlaceholder',
                )}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
              {character ? (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <Select
                      label={tVariants('ageStageLabel')}
                      value={draft.ageStage}
                      onChange={(event) => setDraft({ ...draft, ageStage: event.target.value })}
                      options={[
                        { value: '', label: tVariants('ageStageNone') },
                        ...keysOf(AGE_STAGES).map((key) => ({
                          value: key,
                          label: tVariants(AGE_STAGES[key].labelKey),
                        })),
                      ]}
                    />
                    <Select
                      label={tVariants('periodLabel')}
                      value={draft.period}
                      onChange={(event) => setDraft({ ...draft, period: event.target.value })}
                      options={[
                        { value: '', label: tPresets('presets.none') },
                        ...keysOf(SCENE_PERIODS).map((key) => ({
                          value: key,
                          label: tPresets(`presets.${SCENE_PERIODS[key].labelKey}`),
                        })),
                      ]}
                    />
                  </div>
                  <TextInput
                    label={tVariants('outfitLabel')}
                    value={draft.outfit}
                    maxLength={LOOK_ATTRIBUTE_LIMITS.outfit}
                    onChange={(event) => setDraft({ ...draft, outfit: event.target.value })}
                  />
                  <TextInput
                    label={tVariants('stateLabel')}
                    value={draft.state}
                    maxLength={LOOK_ATTRIBUTE_LIMITS.state}
                    onChange={(event) => setDraft({ ...draft, state: event.target.value })}
                  />
                  <TextArea
                    label={tVariants('lookDescription')}
                    value={draft.description}
                    maxLength={2000}
                    className="min-h-16"
                    onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                  />
                </>
              ) : kind === 'prop' ? (
                <PropPresetFields
                  presets={draft.propPresets}
                  onChange={(next) => setDraft({ ...draft, propPresets: next })}
                />
              ) : (
                <ScenePresetFields
                  presets={draft.scenePresets}
                  onChange={(next) => setDraft({ ...draft, scenePresets: next })}
                />
              )}
            </div>
          )}
          <TextArea
            label={t('deriveExtra')}
            value={extra}
            maxLength={500}
            className="min-h-16"
            onChange={(event) => setExtra(event.target.value)}
          />
          {current?.relations?.length ? (
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
              {t('deriveRelations')}
              {current.relations.map((relation: AssetRelation) => (
                <span
                  key={relation}
                  className="rounded-full border px-2 py-0.5 text-text"
                  style={{ borderColor: RELATION_COLOR[relation] }}
                >
                  {t(relationLabelKey(relation))}
                </span>
              ))}
            </div>
          ) : null}
        </>
      )}

      {error ? <ErrorNotice title={error} /> : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted" aria-live="polite">
          {current
            ? t('quote', { credits: current.credits, available: current.available_credits })
            : ready
              ? t('quoting')
              : null}
        </p>
        <Button
          size="sm"
          icon={<IconSparkle className="size-3.5" />}
          loading={busy}
          disabled={!ready || !current?.sufficient}
          onClick={() => void submit()}
        >
          {mode === 'adjust' ? t('adjustSubmit') : t('deriveSubmit')}
        </Button>
      </div>
    </div>
  );
}
