'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import type { CardKind } from '@/components/library/entry-actions';
import { SceneMatrixDialog } from '@/components/scenes/scene-matrix-dialog';
import { Button } from '@/components/ui/button';
import { TextArea, TextInput } from '@/components/ui/field';
import { IconPlus, IconSparkle } from '@/components/ui/icons';
import type { AssetGraph } from '@/lib/api/types';

import { RELATION_COLOR, RELATIONS_BY_KIND, relationLabelKey } from '../relations';
import type { AssetGraphActions } from '../use-asset-graph';
import { InspectorSection } from './section';

/** Nothing selected: the card at a glance, a new look, the legend and how
 * to work the graph. */
export function CardInspector({
  graph,
  kind,
  busy,
  actions,
  onCreated,
  onOpenPortrait,
}: {
  graph: AssetGraph;
  kind: CardKind;
  busy: boolean;
  actions: AssetGraphActions;
  onCreated: (variantId: string) => void;
  /** 生成定妆照: the workspace's 创作 tab on the portrait slot. */
  onOpenPortrait?: () => void;
}) {
  const t = useTranslations('assetGraph');
  const tVariants = useTranslations('assetVariants');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [matrixOpen, setMatrixOpen] = useState(false);
  const variants = graph.variants ?? [];
  const entries = variants.flatMap((v) => v.entries ?? []);
  const hasPortrait = entries.some(
    (entry) => entry.entry_type === 'identity_portrait' && entry.status !== 'candidate',
  );
  const character = kind === 'character';
  const atCap = graph.caps.max_variants != null && variants.length >= graph.caps.max_variants;

  const create = async () => {
    const created = await actions.createVariant({
      name: name.trim(),
      description: description.trim() || null,
    });
    if (created) {
      setName('');
      setDescription('');
      onCreated(created.id);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">{graph.name}</h2>
        <p className="mt-1 text-xs text-muted">
          {t('cardStats', {
            looks: variants.length,
            images: entries.length,
            relations: (graph.edges ?? []).length,
          })}
        </p>
        {graph.description ? (
          <p className="mt-2 line-clamp-4 whitespace-pre-line text-xs text-muted">
            {graph.description}
          </p>
        ) : null}
      </div>

      {character && onOpenPortrait && !hasPortrait ? (
        <div className="flex flex-col gap-2 rounded-[var(--radius-sm)] border border-dashed border-border p-3">
          <p className="text-xs text-muted">{tVariants('portraitFirst')}</p>
          <Button
            size="sm"
            variant="secondary"
            className="self-start"
            icon={<IconSparkle className="size-3.5" />}
            onClick={onOpenPortrait}
          >
            {tVariants('generatePortrait')}
          </Button>
        </div>
      ) : null}

      <InspectorSection title={t(character ? 'newLook' : 'newVariant')}>
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) void create();
          }}
        >
          <TextInput
            label={tVariants('name')}
            value={name}
            maxLength={40}
            disabled={atCap}
            placeholder={tVariants(
              character
                ? 'lookPlaceholder'
                : kind === 'prop'
                  ? 'propVariantPlaceholder'
                  : 'variantPlaceholder',
            )}
            onChange={(event) => setName(event.target.value)}
          />
          <TextArea
            label={tVariants(character ? 'lookDescription' : 'variantDescription')}
            value={description}
            maxLength={2000}
            disabled={atCap}
            className="min-h-16"
            onChange={(event) => setDescription(event.target.value)}
          />
          {atCap ? (
            <p className="text-xs text-muted">
              {t('lookCapReached', { max: graph.caps.max_variants ?? 0 })}
            </p>
          ) : null}
          <Button
            type="submit"
            size="sm"
            className="self-start"
            icon={<IconPlus className="size-3.5" />}
            loading={busy}
            disabled={!name.trim() || atCap}
          >
            {tVariants('create')}
          </Button>
        </form>
        {kind === 'scene' ? (
          <Button
            size="sm"
            variant="secondary"
            className="self-start"
            icon={<IconSparkle className="size-3.5" />}
            onClick={() => setMatrixOpen(true)}
          >
            {tVariants('matrixOpen')}
          </Button>
        ) : null}
      </InspectorSection>

      <InspectorSection title={t('legendTitle')}>
        <ul className="grid grid-cols-2 gap-1.5 text-xs">
          {RELATIONS_BY_KIND[kind].map((relation) => (
            <li key={relation} className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-0.5 w-5 rounded"
                style={{ background: RELATION_COLOR[relation] }}
              />
              {t(relationLabelKey(relation))}
            </li>
          ))}
        </ul>
        <ul className="flex flex-col gap-1 text-xs text-muted">
          <li>{t('legendManual')}</li>
          <li>{t('legendAuto')}</li>
          <li>{t('legendHint')}</li>
        </ul>
      </InspectorSection>

      <InspectorSection title={t('howToTitle')}>
        <ul className="list-disc space-y-1 pl-4 text-xs text-muted">
          <li>{t('howToSelect')}</li>
          <li>{t('howToConnect')}</li>
          <li>{t('howToExpand')}</li>
        </ul>
      </InspectorSection>

      {kind === 'scene' ? (
        <SceneMatrixDialog
          sceneId={graph.card_id}
          open={matrixOpen}
          onClose={() => setMatrixOpen(false)}
          onProgress={() => void actions.refresh()}
        />
      ) : null}
    </div>
  );
}
