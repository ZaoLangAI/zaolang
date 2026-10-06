'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { AssetGraphWorkspace } from '@/components/asset-graph/asset-graph-workspace';
import { useAssetGraph } from '@/components/asset-graph/use-asset-graph';
import type { CardKind } from '@/components/library/entry-actions';
import { Button } from '@/components/ui/button';
import { ErrorNotice } from '@/components/ui/primitives';
import type { AssetGraph } from '@/lib/api/types';
import { cn } from '@/lib/cn';

import { CreateTab } from './create-tab';
import type { WorkspaceTab } from './tabs';

const PENDING_POLL_MS = 3000;

/**
 * A card's workspace (`/create/{characters|scenes|props}/[id]`): 创作 — the
 * slot board (AC-5) — then 图谱 and, for a character, 音色 (the relation
 * graph, RL-P5/P8). All tabs share one graph store; while jobs are filing
 * into the card it is refetched so finished images replace the placeholders.
 */
export function AssetWorkspace({
  kind,
  initial,
  initialTab,
  initialVariantId,
  initialSlotId,
  initialSkillId,
}: {
  kind: CardKind;
  initial: AssetGraph;
  initialTab?: WorkspaceTab | null;
  /** `?look=` / `?variant=`. */
  initialVariantId?: string | null;
  /** `?slot=`: preselect a 创作 slot. */
  initialSlotId?: string | null;
  /** `?skillId=`: the style skill the 创作 slot panel starts on. */
  initialSkillId?: string | null;
}) {
  const t = useTranslations('assetWorkspace');
  const tGraph = useTranslations('assetGraph');
  const store = useAssetGraph(kind, initial);
  const { graph, busy, error, actions, clearError } = store;
  const tabs: WorkspaceTab[] =
    kind === 'character' ? ['create', 'looks', 'voices'] : ['create', 'looks'];
  const [tab, setTab] = useState<WorkspaceTab>(
    initialTab && tabs.includes(initialTab) ? initialTab : 'create',
  );
  // A look (and slot) the graph asked to generate for — the 创作 tab mounts
  // on it. The graph's 生成 / 生成定妆照 land here, never in a studio.
  const [createTarget, setCreateTarget] = useState<{
    variantId: string;
    slotId: string | null;
  } | null>(null);
  const openCreate = (variantId: string, slotId: string | null = null) => {
    setCreateTarget({ variantId, slotId });
    setTab('create');
  };
  const defaultVariantId =
    (graph.variants ?? []).find((variant) => variant.is_default)?.id ?? graph.variants?.[0]?.id;

  const pendingCount = graph.pending?.length ?? 0;
  const { refresh } = actions;
  useEffect(() => {
    if (!pendingCount) return;
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, PENDING_POLL_MS);
    return () => window.clearInterval(timer);
  }, [pendingCount, refresh]);

  return (
    <div className="flex flex-col gap-4">
      <div
        role="tablist"
        aria-label={tGraph('tabsLabel')}
        className="flex gap-1 self-start rounded-[var(--radius-sm)] bg-surface-soft p-1"
      >
        {tabs.map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={cn(
              'rounded-[var(--radius-sm)] px-3 py-1.5 text-sm transition-colors focus-visible:outline-2',
              tab === value ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-text',
            )}
          >
            {value === 'create'
              ? t('tabCreate')
              : value === 'looks'
                ? t(`tabGraph.${kind}`, { count: (graph.variants ?? []).length })
                : tGraph('tabVoices', { count: (graph.voices ?? []).length })}
          </button>
        ))}
      </div>

      {tab === 'create' ? (
        <>
          {error ? (
            <ErrorNotice
              title={error}
              action={
                <Button size="sm" variant="ghost" onClick={clearError}>
                  {tGraph('dismiss')}
                </Button>
              }
            />
          ) : null}
          <CreateTab
            kind={kind}
            graph={graph}
            actions={actions}
            busy={busy}
            initialVariantId={createTarget?.variantId ?? initialVariantId}
            initialSlotId={createTarget ? createTarget.slotId : initialSlotId}
            initialSkillId={initialSkillId}
          />
        </>
      ) : (
        <AssetGraphWorkspace
          kind={kind}
          store={store}
          tab={tab}
          initialLookId={initialVariantId}
          onOpenCreate={(variant) => openCreate(variant.id)}
          onOpenPortrait={
            kind === 'character' && defaultVariantId
              ? () => openCreate(defaultVariantId, 'portrait')
              : undefined
          }
        />
      )}
    </div>
  );
}
