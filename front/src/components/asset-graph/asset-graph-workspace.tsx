'use client';

import dynamic from 'next/dynamic';
import { useTranslations } from 'next-intl';
import { useCallback, useState } from 'react';

import type { CardKind } from '@/components/library/entry-actions';
import { Button } from '@/components/ui/button';
import { ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { Sheet } from '@/components/ui/sheet';
import { useToast } from '@/components/ui/toast';
import type { AssetGraph, AssetVariant } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { useGenerationModels } from '@/lib/use-generation-models';
import { useMinWidth } from '@/lib/use-media-query';

import { AssetGraphOutline } from './asset-graph-outline';
import type { GraphSelection } from './graph-model';
import { CardInspector } from './inspector/card-inspector';
import { EdgeInspector } from './inspector/edge-inspector';
import { EntryInspector } from './inspector/entry-inspector';
import { LookInspector } from './inspector/look-inspector';
import { useNodeNames } from './inspector/node-names';
import { VoiceInspector } from './inspector/voice-inspector';
import { VoicesPanel } from './inspector/voices-panel';
import { RelationPickerDialog } from './relation-picker';
import type { AssetGraphStore } from './use-asset-graph';

// React Flow + dagre load only with the canvas, never with the page shell.
const AssetGraphCanvas = dynamic(
  () => import('./asset-graph-canvas').then((module) => module.AssetGraphCanvas),
  { ssr: false, loading: () => <Skeleton className="h-full w-full rounded-none" /> },
);

/** Auto-expand a small card so its images are visible on arrival. */
const AUTO_EXPAND_LOOKS = 3;
const AUTO_EXPAND_ENTRIES = 9;

function initialExpanded(graph: AssetGraph, lookId?: string | null): Set<string> {
  const variants = graph.variants ?? [];
  const open = new Set<string>();
  if (variants.length <= AUTO_EXPAND_LOOKS) {
    for (const variant of variants) {
      const count = (variant.entries ?? []).length;
      if (count > 0 && count <= AUTO_EXPAND_ENTRIES) open.add(variant.id);
    }
  }
  if (lookId) open.add(lookId);
  return open;
}

interface ConnectDraft {
  level: 'variant' | 'entry' | 'voice';
  sourceId: string;
  targetId: string;
}

/**
 * The card management page body: the relation graph (canvas at `md` and
 * up, an indented outline below), with a docked inspector for whatever is
 * selected — the card itself, a look / variant, an image or a relation.
 */
export function AssetGraphWorkspace({
  kind,
  store,
  tab,
  initialLookId,
  generateHref,
  portraitHref,
}: {
  kind: CardKind;
  /** The card's graph and writes, shared with the 创作 tab
   * (`features/asset-workspace/asset-workspace.tsx`), which also polls it
   * while jobs are pending. */
  store: AssetGraphStore;
  /** 造型图谱 or 音色 — the outer workspace's tabs pick it. */
  tab: 'looks' | 'voices';
  /** `?look=`: select and expand this look on arrival. */
  initialLookId?: string | null;
  generateHref: (variant: AssetVariant) => string;
  portraitHref?: string;
}) {
  const t = useTranslations('assetGraph');
  const { notify } = useToast();
  const wide = useMinWidth('md');
  const { graph, busy, error, actions, clearError } = store;
  const initial = graph;
  const names = useNodeNames(graph);
  const lookExists = Boolean(initialLookId && graph.variants?.some((v) => v.id === initialLookId));
  const [expanded, setExpanded] = useState<Set<string>>(() =>
    initialExpanded(initial, lookExists ? initialLookId : null),
  );
  const [selection, setSelection] = useState<GraphSelection>(() =>
    lookExists && initialLookId ? { type: 'variant', id: initialLookId } : { type: 'card' },
  );
  const [connect, setConnect] = useState<ConnectDraft | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  // Switching tab (音色 has its own graph) resets the selection.
  const [seenTab, setSeenTab] = useState(tab);
  if (seenTab !== tab) {
    setSeenTab(tab);
    setSelection({ type: 'card' });
    setSheetOpen(false);
  }
  const audioModels = useGenerationModels(
    kind === 'character' ? 'audio_generation' : 'text_to_image',
  );
  const voiceModels = kind === 'character' ? audioModels : [];

  const toggle = useCallback((variantId: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(variantId)) next.delete(variantId);
      else next.add(variantId);
      return next;
    });
  }, []);
  const toggleAll = (expand: boolean) =>
    setExpanded(expand ? new Set((graph.variants ?? []).map((v) => v.id)) : new Set());

  const select = (next: GraphSelection) => {
    setSelection(next);
    if (!wide) setSheetOpen(next.type !== 'card' || sheetOpen);
  };
  const selectNode = (level: 'variant' | 'entry' | 'voice', id: string) =>
    select(
      level === 'variant'
        ? { type: 'variant', id }
        : level === 'voice'
          ? { type: 'voice', id }
          : { type: 'entry', id },
    );
  // The selection can outlive its node (deleted here or in another tab).
  const variants = graph.variants ?? [];
  const selectedVariant =
    selection.type === 'variant' ? variants.find((v) => v.id === selection.id) : undefined;
  const entryOwner =
    selection.type === 'entry'
      ? variants.find((v) => (v.entries ?? []).some((e) => e.id === selection.id))
      : undefined;
  const selectedEntry = entryOwner?.entries?.find(
    (e) => selection.type === 'entry' && e.id === selection.id,
  );
  const selectedEdge =
    selection.type === 'edge' ? graph.edges?.find((e) => e.id === selection.id) : undefined;
  const selectedVoice =
    selection.type === 'voice' ? graph.voices?.find((v) => v.id === selection.id) : undefined;

  const toCard = () => select({ type: 'card' });

  const inspector = selectedVoice ? (
    <VoiceInspector
      key={selectedVoice.id}
      graph={graph}
      kind={kind}
      voice={selectedVoice}
      models={voiceModels}
      busy={busy}
      actions={actions}
      onSelectEdge={(id) => select({ type: 'edge', id })}
      onDeleted={toCard}
      onCreated={(id) => select({ type: 'voice', id })}
    />
  ) : selectedVariant ? (
    <LookInspector
      key={selectedVariant.id}
      graph={graph}
      kind={kind}
      variant={selectedVariant}
      expanded={expanded.has(selectedVariant.id)}
      busy={busy}
      actions={actions}
      onToggle={() => toggle(selectedVariant.id)}
      onSelectEdge={(id) => select({ type: 'edge', id })}
      onDeleted={toCard}
      generateHref={generateHref}
    />
  ) : selectedEntry && entryOwner ? (
    <EntryInspector
      key={selectedEntry.id}
      graph={graph}
      kind={kind}
      entry={selectedEntry}
      variant={entryOwner}
      busy={busy}
      actions={actions}
      onSelectEdge={(id) => select({ type: 'edge', id })}
      onSelectVersion={(id) => select({ type: 'entry', id })}
      onDeleted={toCard}
      onGenerated={(response) => {
        if (response.variant_id) {
          const look = response.variant_id;
          setExpanded((current) => new Set(current).add(look));
        }
        void actions.refresh();
      }}
    />
  ) : selectedEdge ? (
    <EdgeInspector
      key={selectedEdge.id}
      graph={graph}
      kind={kind}
      edge={selectedEdge}
      busy={busy}
      actions={actions}
      onSelectNode={selectNode}
      onDeleted={toCard}
    />
  ) : tab === 'voices' ? (
    <VoicesPanel
      graph={graph}
      voiceDescription={graph.voice_description ?? null}
      models={voiceModels}
      busy={busy}
      actions={actions}
      onCreated={(id) => select({ type: 'voice', id })}
    />
  ) : (
    <CardInspector
      graph={graph}
      kind={kind}
      busy={busy}
      actions={actions}
      portraitHref={portraitHref}
      onCreated={(id) => {
        setExpanded((current) => new Set(current).add(id));
        select({ type: 'variant', id });
      }}
    />
  );

  return (
    <div className="flex flex-col gap-3">
      {error ? (
        <ErrorNotice
          title={error}
          action={
            <Button size="sm" variant="ghost" onClick={clearError}>
              {t('dismiss')}
            </Button>
          }
        />
      ) : null}

      {/* Narrow screens: outline + inspector sheet. */}
      <div className="flex flex-col gap-3 md:hidden">
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          onClick={() => {
            setSelection({ type: 'card' });
            setSheetOpen(true);
          }}
        >
          {t('cardPanel')}
        </Button>
        {tab === 'voices' ? (
          <VoiceOutline graph={graph} selection={selection} onSelect={select} />
        ) : (
          <AssetGraphOutline graph={graph} kind={kind} selection={selection} onSelect={select} />
        )}
        {!wide ? (
          <Sheet
            open={sheetOpen}
            onClose={() => setSheetOpen(false)}
            title={selection.type === 'card' ? graph.name : t('inspectorTitle')}
            loading={busy}
          >
            {inspector}
          </Sheet>
        ) : null}
      </div>

      {/* `md` and up: canvas + docked inspector. */}
      <div className="hidden h-[calc(100dvh-14rem)] min-h-[560px] overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft md:flex">
        <div className="relative min-w-0 flex-1">
          {wide ? (
            <AssetGraphCanvas
              key={tab}
              mode={tab}
              graph={graph}
              expanded={expanded}
              selection={selection}
              onSelect={select}
              onToggle={toggle}
              onToggleAll={toggleAll}
              onConnect={(level, sourceId, targetId) => setConnect({ level, sourceId, targetId })}
              onInvalidConnect={() => notify(t('connectMixed'), 'error')}
            />
          ) : (
            <Skeleton className="h-full w-full rounded-none" />
          )}
        </div>
        <aside
          aria-label={t('inspectorTitle')}
          aria-busy={busy}
          className="w-[360px] shrink-0 overflow-y-auto border-l border-border bg-surface p-4"
        >
          {selection.type !== 'card' ? (
            <Button size="sm" variant="ghost" className="mb-3" onClick={toCard}>
              {t('backToCard')}
            </Button>
          ) : null}
          {inspector}
        </aside>
      </div>

      {connect ? (
        <RelationPickerDialog
          kind={kind}
          voices={connect.level === 'voice'}
          busy={busy}
          sourceName={names(connect.level, connect.sourceId)}
          targetName={names(connect.level, connect.targetId)}
          onCancel={() => setConnect(null)}
          onConfirm={(draft) =>
            void actions
              .createEdge({
                level: connect.level,
                source_id: connect.sourceId,
                target_id: connect.targetId,
                relations: draft.relations,
                label: draft.label.trim() || null,
              })
              .then((edge) => {
                setConnect(null);
                if (edge) setSelection({ type: 'edge', id: edge.id });
              })
          }
        />
      ) : null}
    </div>
  );
}

/** The 音色 tab below `md`: voices as a plain list (the canvas is wide-only). */
function VoiceOutline({
  graph,
  selection,
  onSelect,
}: {
  graph: AssetGraph;
  selection: GraphSelection;
  onSelect: (selection: GraphSelection) => void;
}) {
  const t = useTranslations('assetGraph');
  const voices = graph.voices ?? [];
  if (!voices.length) return <p className="text-sm text-muted">{t('noVoices')}</p>;
  return (
    <ul className="flex flex-col gap-2">
      {voices.map((voice) => (
        <li key={voice.id}>
          <button
            type="button"
            onClick={() => onSelect({ type: 'voice', id: voice.id })}
            className={cn(
              'flex w-full flex-col items-start gap-0.5 rounded-[var(--radius-md)] border bg-surface p-3 text-left focus-visible:outline-2',
              selection.type === 'voice' && selection.id === voice.id
                ? 'border-primary ring-2 ring-primary/30'
                : 'border-border',
            )}
          >
            <span className="text-sm font-semibold">
              {voice.name}
              {voice.is_default ? ` · ${t('defaultBadge')}` : ''}
            </span>
            <span className="text-[11px] text-muted">
              {voice.source === 'clone'
                ? t('voiceCloneSummary')
                : [voice.model, voice.voice].filter(Boolean).join(' · ')}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
