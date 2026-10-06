'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { LookFillDialog } from '@/components/characters/look-fill-dialog';
import type { CardKind } from '@/components/library/entry-actions';
import { PropPresetFields, propPresetsOf } from '@/components/library/prop-preset-fields';
import { ScenePresetFields } from '@/components/library/scene-preset-fields';
import { VariantAttributesForm } from '@/components/library/variant-attributes-form';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Select, TextArea, TextInput } from '@/components/ui/field';
import { IconSparkle } from '@/components/ui/icons';
import { Badge } from '@/components/ui/primitives';
import type { ScenePresets } from '@/features/image-assets/vocabulary';
import type { AssetGraph, AssetVariant } from '@/lib/api/types';

import type { AssetGraphActions } from '../use-asset-graph';
import { AddRelationForm, RelationsList } from './relations-list';
import { InspectorSection, UploadButton } from './section';

/** A selected look / variant: its text, attributes, images and relations.
 * Mounted per look (keyed), so its drafts start from that look. */
export function LookInspector({
  graph,
  kind,
  variant,
  expanded,
  busy,
  actions,
  onToggle,
  onSelectEdge,
  onDeleted,
  onOpenCreate,
}: {
  graph: AssetGraph;
  kind: CardKind;
  variant: AssetVariant;
  expanded: boolean;
  busy: boolean;
  actions: AssetGraphActions;
  onToggle: () => void;
  onSelectEdge: (edgeId: string) => void;
  onDeleted: () => void;
  /** 生成: open this look / variant on the workspace's 创作 tab. */
  onOpenCreate?: (variant: AssetVariant) => void;
}) {
  const t = useTranslations('assetGraph');
  const tVariants = useTranslations('assetVariants');
  const tActions = useTranslations('actions');
  const [name, setName] = useState(variant.name);
  const [description, setDescription] = useState(variant.description ?? '');
  const [fillOpen, setFillOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const dirty = name.trim() !== variant.name || description !== (variant.description ?? '');
  const character = kind === 'character';
  const firstEntryType = character ? 'other' : (variant.entries ?? []).length ? 'shot' : 'master';

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h2 className="min-w-0 flex-1 truncate text-base font-semibold">{variant.name}</h2>
        {variant.is_default ? <Badge tone="primary">{t('defaultBadge')}</Badge> : null}
      </div>

      <InspectorSection title={t('sectionBasics')}>
        <TextInput
          label={tVariants('name')}
          value={name}
          maxLength={40}
          onChange={(event) => setName(event.target.value)}
        />
        <TextArea
          label={tVariants(character ? 'lookDescription' : 'variantDescription')}
          value={description}
          maxLength={2000}
          className="min-h-20"
          onChange={(event) => setDescription(event.target.value)}
        />
        <Button
          size="sm"
          className="self-start"
          disabled={!dirty || !name.trim()}
          loading={busy}
          onClick={() => void actions.updateVariant(variant.id, { name: name.trim(), description })}
        >
          {tVariants('save')}
        </Button>
      </InspectorSection>

      <InspectorSection title={t('sectionAttributes')}>
        {kind === 'scene' ? (
          <ScenePresetFields
            presets={(variant.presets ?? {}) as ScenePresets}
            onChange={(next) => void actions.updateVariant(variant.id, { presets: next })}
          />
        ) : kind === 'prop' ? (
          <PropPresetFields
            presets={propPresetsOf(variant.presets)}
            onChange={(next) => void actions.updateVariant(variant.id, { presets: next })}
          />
        ) : null}
        <VariantAttributesForm
          kind={kind}
          variant={variant}
          busy={busy}
          onSave={(body) => void actions.updateVariant(variant.id, body)}
        />
      </InspectorSection>

      {character ? (
        <InspectorSection title={t('sectionLookVoice')}>
          <Select
            label={t('lookVoice')}
            value={variant.voice_id ?? ''}
            onChange={(event) =>
              void actions.updateVariant(
                variant.id,
                event.target.value ? { voice_id: event.target.value } : { clear_voice: true },
              )
            }
            options={[
              { value: '', label: t('lookVoiceDefault') },
              ...(graph.voices ?? []).map((voice) => ({ value: voice.id, label: voice.name })),
            ]}
          />
        </InspectorSection>
      ) : null}

      <InspectorSection title={t('sectionImages')}>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={onToggle}>
            {expanded ? t('collapse') : t('expand')}
          </Button>
          <UploadButton
            label={tVariants('upload')}
            onFile={(file) => void actions.upload(variant.id, file, firstEntryType)}
          />
          {character && !variant.is_default ? (
            <UploadButton
              label={tVariants('uploadOutfit')}
              title={tVariants('uploadOutfitHint')}
              onFile={(file) => void actions.upload(variant.id, file, 'outfit_detail')}
            />
          ) : null}
          {character ? (
            <Button
              size="sm"
              variant="secondary"
              icon={<IconSparkle className="size-3.5" />}
              onClick={() => setFillOpen(true)}
            >
              {tVariants('fillOpen')}
            </Button>
          ) : null}
          {onOpenCreate ? (
            <Button size="sm" variant="ghost" onClick={() => onOpenCreate(variant)}>
              {t('openInCreate')}
            </Button>
          ) : null}
        </div>
      </InspectorSection>

      <InspectorSection title={t('sectionRelations')}>
        <RelationsList
          graph={graph}
          level="variant"
          nodeId={variant.id}
          onSelectEdge={onSelectEdge}
        />
        <AddRelationForm
          graph={graph}
          kind={kind}
          level="variant"
          nodeId={variant.id}
          busy={busy}
          onCreate={actions.createEdge}
        />
      </InspectorSection>

      {!variant.is_default ? (
        <InspectorSection title={t('sectionManage')}>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void actions.updateVariant(variant.id, { make_default: true })}
            >
              {tVariants('makeDefault')}
            </Button>
            <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>
              {tVariants(character ? 'deleteLook' : 'deleteVariant')}
            </Button>
          </div>
        </InspectorSection>
      ) : null}

      {character && fillOpen ? (
        <LookFillDialog
          characterId={graph.card_id}
          look={variant}
          open
          onClose={() => setFillOpen(false)}
          onProgress={() => void actions.refresh()}
        />
      ) : null}
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t('deleteLookTitle', { name: variant.name })}
        description={t('deleteLookHint')}
        confirmLabel={tActions('delete')}
        cancelLabel={tActions('cancel')}
        busy={busy}
        onConfirm={() =>
          void actions.deleteVariant(variant.id).then((done) => {
            setConfirmDelete(false);
            if (done !== undefined) onDeleted();
          })
        }
      />
    </div>
  );
}
