'use client';

import { useTranslations } from 'next-intl';

import { TextInput } from '@/components/ui/field';
import type { AssetRelation } from '@/lib/api/types';
import { cn } from '@/lib/cn';

import type { CardKind } from '@/components/library/entry-actions';

import {
  MAX_EDGE_LABEL_LENGTH,
  MAX_RELATIONS_PER_EDGE,
  RELATION_COLOR,
  RELATIONS_BY_KIND,
  relationLabelKey,
} from './relations';

export interface RelationDraft {
  relations: AssetRelation[];
  label: string;
}

export function relationDraftValid(draft: RelationDraft): boolean {
  return (
    draft.relations.length > 0 && (!draft.relations.includes('custom') || draft.label.trim() !== '')
  );
}

/** Relation-type chips (multi-select, per card kind) plus the label a
 * custom relation needs — shared by the connect dialog, the add-relation
 * form and the edge inspector. */
export function RelationFields({
  kind,
  value,
  onChange,
}: {
  kind: CardKind;
  value: RelationDraft;
  onChange: (next: RelationDraft) => void;
}) {
  const t = useTranslations('assetGraph');
  const toggle = (relation: AssetRelation) => {
    const on = value.relations.includes(relation);
    if (!on && value.relations.length >= MAX_RELATIONS_PER_EDGE) return;
    onChange({
      ...value,
      relations: on
        ? value.relations.filter((item) => item !== relation)
        : [...value.relations, relation],
    });
  };
  return (
    <div className="flex flex-col gap-3">
      <fieldset>
        <legend className="mb-1.5 text-xs font-medium text-muted">{t('relationTypes')}</legend>
        <div className="flex flex-wrap gap-1.5">
          {RELATIONS_BY_KIND[kind].map((relation) => {
            const on = value.relations.includes(relation);
            return (
              <button
                key={relation}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(relation)}
                style={on ? { borderColor: RELATION_COLOR[relation] } : undefined}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-2',
                  on ? 'bg-surface-soft text-text' : 'border-border text-muted hover:text-text',
                )}
              >
                <span
                  aria-hidden
                  className="size-2 rounded-full"
                  style={{ background: RELATION_COLOR[relation] }}
                />
                {t(relationLabelKey(relation))}
              </button>
            );
          })}
        </div>
      </fieldset>
      <TextInput
        label={t('relationLabel')}
        hint={
          value.relations.includes('custom') ? t('relationLabelRequired') : t('relationLabelHint')
        }
        value={value.label}
        maxLength={MAX_EDGE_LABEL_LENGTH}
        onChange={(event) => onChange({ ...value, label: event.target.value })}
      />
    </div>
  );
}
