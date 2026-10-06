'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import type { AssetGraphActions } from '@/components/asset-graph/use-asset-graph';
import { LookFillDialog } from '@/components/characters/look-fill-dialog';
import type { CardKind } from '@/components/library/entry-actions';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { IconPlus } from '@/components/ui/icons';
import { Badge } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import type { AssetGraph } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { useMinWidth } from '@/lib/use-media-query';

import { completeness, type SlotState, slotStates } from './completeness';
import { SlotPanel } from './slot-panel';

/**
 * 创作 tab of a card workspace (AC-5): the asset board. The variant rail
 * picks a look / variant / condition; the board shows its standard slots
 * (`kind-config.ts`) with what is filed — approved, candidates waiting for
 * 定稿, running jobs — and the panel generates the selected slot. Below `md`
 * the rail turns into chips and the panel opens in a sheet.
 */
export function CreateTab({
  kind,
  graph,
  actions,
  busy,
  initialVariantId,
  initialSlotId,
}: {
  kind: CardKind;
  graph: AssetGraph;
  actions: AssetGraphActions;
  busy: boolean;
  initialVariantId?: string | null;
  initialSlotId?: string | null;
}) {
  const t = useTranslations('assetWorkspace');
  const wide = useMinWidth('md');
  const variants = useMemo(() => graph.variants ?? [], [graph.variants]);
  const [variantId, setVariantId] = useState<string>(
    () =>
      (initialVariantId && variants.some((v) => v.id === initialVariantId)
        ? initialVariantId
        : variants.find((v) => v.is_default)?.id) ??
      variants[0]?.id ??
      '',
  );
  const [slotId, setSlotId] = useState<string | null>(initialSlotId ?? null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [fillOpen, setFillOpen] = useState(false);
  const [newName, setNewName] = useState('');

  const variant = variants.find((v) => v.id === variantId) ?? variants[0];
  const allEntries = useMemo(() => variants.flatMap((v) => v.entries ?? []), [variants]);
  const states = useMemo(
    () => (variant ? slotStates(kind, variant, allEntries, graph.pending ?? []) : []),
    [kind, variant, allEntries, graph.pending],
  );
  if (!variant) return <p className="text-sm text-muted">{t('noVariants')}</p>;

  const selected =
    states.find((state) => state.slot.id === slotId) ??
    states.find((state) => state.status === 'missing') ??
    states[0];
  const score = completeness(states);

  const pick = (state: SlotState) => {
    setSlotId(state.slot.id);
    if (!wide) setSheetOpen(true);
  };
  const createVariant = async () => {
    const name = newName.trim();
    if (!name) return;
    const created = await actions.createVariant({ name });
    if (created) {
      setNewName('');
      setVariantId(created.id);
      setSlotId(null);
    }
  };

  const panel = selected ? (
    <SlotPanel
      key={`${variant.id}:${selected.slot.id}`}
      kind={kind}
      graph={graph}
      variant={variant}
      state={selected}
      states={states}
      actions={actions}
      onSubmitted={() => {
        setSheetOpen(false);
        void actions.refresh();
      }}
      onFill={kind === 'character' ? () => setFillOpen(true) : undefined}
    />
  ) : null;

  return (
    <div className="flex flex-col gap-4 md:flex-row">
      <div className="flex min-w-0 shrink-0 flex-col gap-2 md:w-48">
        <nav
          aria-label={t(`variantsLabel.${kind}`)}
          className="flex gap-2 overflow-x-auto md:flex-col md:overflow-visible"
        >
          {variants.map((item) => {
            const itemScore = completeness(slotStates(kind, item, allEntries, graph.pending ?? []));
            return (
              <button
                key={item.id}
                type="button"
                aria-current={item.id === variant.id ? 'true' : undefined}
                onClick={() => {
                  setVariantId(item.id);
                  setSlotId(null);
                }}
                className={cn(
                  'flex shrink-0 items-center justify-between gap-2 rounded-[var(--radius-sm)] border px-3 py-2 text-left text-sm focus-visible:outline-2',
                  item.id === variant.id
                    ? 'border-primary bg-primary/10'
                    : 'border-border hover:border-border-strong',
                )}
              >
                <span className="truncate">{item.name}</span>
                <span className="text-[11px] text-muted">
                  {itemScore.done}/{itemScore.total}
                </span>
              </button>
            );
          })}
        </nav>
        <form
          className="flex items-end gap-1 md:flex-col md:items-stretch"
          onSubmit={(event) => {
            event.preventDefault();
            void createVariant();
          }}
        >
          <TextInput
            label={t(`newVariant.${kind}`)}
            value={newName}
            maxLength={40}
            onChange={(event) => setNewName(event.target.value)}
          />
          <Button
            type="submit"
            size="sm"
            variant="secondary"
            icon={<IconPlus className="size-4" />}
            disabled={!newName.trim() || busy}
          >
            {t('add')}
          </Button>
        </form>
      </div>

      <section aria-label={t('boardLabel')} className="min-w-0 flex-1">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">{variant.name}</h2>
          <Badge tone={score.done === score.total ? 'success' : 'neutral'}>
            {t('completeness', { done: score.done, total: score.total })}
          </Badge>
        </div>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          {states.map((state) => (
            <li key={state.slot.id}>
              <SlotCard
                state={state}
                selected={selected?.slot.id === state.slot.id}
                onSelect={() => pick(state)}
              />
            </li>
          ))}
        </ul>
      </section>

      {wide ? (
        <aside
          aria-label={t('panelLabel')}
          className="w-[340px] shrink-0 rounded-[var(--radius-md)] border border-border bg-surface p-4"
        >
          {panel}
        </aside>
      ) : (
        <Sheet
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          title={selected ? t(`slot.${selected.slot.id}`) : t('panelLabel')}
        >
          {panel}
        </Sheet>
      )}

      {kind === 'character' && fillOpen ? (
        <LookFillDialog
          characterId={graph.card_id}
          look={variant}
          open={fillOpen}
          onClose={() => setFillOpen(false)}
          onProgress={() => void actions.refresh()}
        />
      ) : null}
    </div>
  );
}

function SlotCard({
  state,
  selected,
  onSelect,
}: {
  state: SlotState;
  selected: boolean;
  onSelect: () => void;
}) {
  const t = useTranslations('assetWorkspace');
  const shown = state.approved ?? state.candidates[0] ?? null;
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        'flex w-full flex-col gap-1.5 rounded-[var(--radius-md)] border bg-surface p-2 text-left focus-visible:outline-2',
        selected
          ? 'border-primary ring-2 ring-primary/30'
          : 'border-border hover:border-border-strong',
        !state.slot.required && state.status === 'missing' && 'opacity-80',
      )}
    >
      <div
        className={cn(
          'relative aspect-square overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft',
          state.status === 'candidate' && 'border border-dashed border-amber',
        )}
      >
        {shown?.url ? (
          <Image
            src={shown.url}
            alt=""
            fill
            sizes="200px"
            className={cn('object-cover', !state.approved && 'opacity-70')}
          />
        ) : (
          <span className="absolute inset-0 flex items-center justify-center text-xs text-muted">
            {state.status === 'pending' ? t('status.pending') : t('empty')}
          </span>
        )}
        {state.candidates.length ? (
          <span className="absolute right-1 top-1">
            <Badge tone="amber">{t('candidateBadge', { count: state.candidates.length })}</Badge>
          </span>
        ) : null}
      </div>
      <span className="flex items-center justify-between gap-1 text-xs">
        <span className="truncate font-medium">{t(`slot.${state.slot.id}`)}</span>
        <span
          className={cn('shrink-0', state.status === 'approved' ? 'text-success' : 'text-muted')}
        >
          {state.slot.required ? t(`status.${state.status}`) : t('optional')}
        </span>
      </span>
    </button>
  );
}
