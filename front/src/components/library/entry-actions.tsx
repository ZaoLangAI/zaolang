'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';

import { Button, IconButton } from '@/components/ui/button';
import { Select } from '@/components/ui/field';
import { IconCheck, IconTrash } from '@/components/ui/icons';
import { Badge } from '@/components/ui/primitives';
import type { AssetEntry, AssetEntryType, AssetVariant } from '@/lib/api/types';
import { cn } from '@/lib/cn';

export type CardKind = 'character' | 'scene' | 'prop';

export const CHARACTER_ENTRY_TYPES: AssetEntryType[] = [
  'identity_portrait',
  'character_sheet',
  'view',
  'expression_sheet',
  'pose',
  'outfit_detail',
  'prop',
  'other',
];
export const SCENE_ENTRY_TYPES: AssetEntryType[] = ['master', 'shot', 'other'];
/** `PROP_ENTRY_TYPES` (AC-4): hero plate, turntable views, detail shots. */
export const PROP_ENTRY_TYPES: AssetEntryType[] = ['master', 'view', 'shot', 'other'];

/** One filed image with its own actions: 定稿 a candidate; retype, move,
 * anchor or remove an approved one. Shared by the looks panel and the
 * graph inspector. */
export function EntryCard({
  entry,
  variant,
  variants,
  isAnchor,
  entryTypes,
  onUpdate,
  onDelete,
  onAnchor,
  onApprove,
  showImage = true,
}: {
  entry: AssetEntry;
  variant: AssetVariant;
  variants: AssetVariant[];
  isAnchor: boolean;
  entryTypes: AssetEntryType[];
  onUpdate: (body: Record<string, unknown>) => void;
  onDelete: () => void;
  onAnchor: () => void;
  onApprove: () => void;
  /** `false` where the image is already shown large (the graph inspector). */
  showImage?: boolean;
}) {
  const t = useTranslations('assetVariants');
  const candidate = entry.status === 'candidate';
  return (
    <li
      className={cn(
        'flex flex-col gap-1.5 rounded-[var(--radius-sm)] border p-1.5',
        candidate ? 'border-dashed border-border' : 'border-border',
      )}
    >
      {showImage ? (
        <div
          className={cn(
            'relative aspect-square overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft',
            candidate && 'opacity-70',
          )}
        >
          {entry.url ? (
            <Image src={entry.url} alt="" fill sizes="160px" className="object-cover" />
          ) : null}
          {isAnchor ? (
            <span className="absolute left-1 top-1">
              <Badge tone="primary">{t('anchor')}</Badge>
            </span>
          ) : candidate ? (
            <span className="absolute left-1 top-1">
              <Badge>{t('candidate')}</Badge>
            </span>
          ) : null}
        </div>
      ) : null}
      {candidate ? (
        <Button size="sm" onClick={onApprove} title={t('approveHint')}>
          {t('approve')}
        </Button>
      ) : (
        <>
          <Select
            label={t('entryType')}
            value={entry.entry_type}
            onChange={(event) => onUpdate({ entry_type: event.target.value })}
            options={entryTypes.map((type) => ({ value: type, label: t(`type.${type}`) }))}
          />
          {variants.length > 1 ? (
            <Select
              label={t('moveTo')}
              value={variant.id}
              onChange={(event) => onUpdate({ variant_id: event.target.value })}
              options={variants.map((v) => ({ value: v.id, label: v.name }))}
            />
          ) : null}
        </>
      )}
      <div className="flex justify-between">
        {candidate ? (
          <span />
        ) : (
          <IconButton size="sm" label={t('setAnchor')} disabled={isAnchor} onClick={onAnchor}>
            <IconCheck className="size-4" />
          </IconButton>
        )}
        <IconButton size="sm" variant="danger" label={t('removeEntry')} onClick={onDelete}>
          <IconTrash className="size-4" />
        </IconButton>
      </div>
    </li>
  );
}
