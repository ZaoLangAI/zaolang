'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import type { StudioSource } from '@/components/studio/generation-studio';
import { IconClose, IconUpload } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { type Asset, uploadFile } from '@/lib/upload';

/**
 * Left rail of the studio: what the new version inherits, plus anything the
 * user adds.
 *
 * Inherited materials are not removable — they are the licence-bearing part of
 * the remix, and dropping them would break the attribution the lineage
 * promises.
 */
export function SourceMaterialRail({
  source,
  uploads,
  onUploaded,
  onRemove,
}: {
  source?: StudioSource;
  uploads: Asset[];
  onUploaded: (asset: Asset) => void;
  onRemove: (assetId: string) => void;
}) {
  const t = useTranslations('remixPage');
  const tStates = useTranslations('states');
  const { notify } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const inherited = source
    ? [
        {
          id: 'first-frame',
          label: t('firstFrame'),
          url: source.work.current_version?.cover_url ?? source.work.cover_url,
        },
        ...(source.params.style_tags ?? []).slice(0, 2).map((tag, index) => ({
          id: `style-${tag}`,
          label: index === 0 ? t('styleReference') : t('lightReference'),
          url: source.work.cover_url,
        })),
      ]
    : [];

  const total = inherited.length + uploads.length;

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      onUploaded(await uploadFile(file, 'generation_reference'));
    } catch {
      notify(tStates('error'), 'error');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <aside className="lg:border-r lg:border-border lg:pr-4">
      <h2 className="text-sm font-semibold">{t('sourceMaterials', { count: total })}</h2>
      <p className="mt-1 text-[11px] text-muted">{t('sourceHint')}</p>

      <ul className="mt-4 flex gap-3 overflow-x-auto lg:flex-col lg:overflow-visible">
        {inherited.map((item) => (
          <li key={item.id} className="w-28 shrink-0 lg:w-full">
            <Thumb url={item.url} label={item.label} />
          </li>
        ))}

        {uploads.map((asset) => (
          <li key={asset.id} className="relative w-28 shrink-0 lg:w-full">
            <Thumb url={asset.url} label={t('addMaterial')} />
            <button
              type="button"
              aria-label={`${t('addMaterial')} ✕`}
              onClick={() => onRemove(asset.id)}
              className="absolute right-1.5 top-1.5 grid size-6 place-items-center rounded-full bg-surface-raised/90 text-muted hover:text-text"
            >
              <IconClose className="size-3.5" />
            </button>
          </li>
        ))}

        <li className="w-28 shrink-0 lg:w-full">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-1.5 rounded-[var(--radius-sm)] border border-dashed border-border text-[11px] text-muted transition-colors hover:border-border-strong hover:text-text disabled:opacity-60"
          >
            {busy ? <Spinner className="size-4" /> : <IconUpload className="size-4" />}
            {t('addMaterial')}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            className="sr-only"
            onChange={(event) => void pick(event.target.files?.[0])}
          />
        </li>
      </ul>
    </aside>
  );
}

function Thumb({ url, label }: { url?: string | null; label: string }) {
  return (
    <figure className="overflow-hidden rounded-[var(--radius-sm)] border border-border">
      <div className="relative aspect-[4/3] bg-surface-soft">
        {url ? <Image src={url} alt="" fill sizes="160px" className="object-cover" /> : null}
      </div>
      <figcaption className="truncate bg-surface px-2 py-1.5 text-[11px] text-muted">
        {label}
      </figcaption>
    </figure>
  );
}
