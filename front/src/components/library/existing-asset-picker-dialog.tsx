'use client';

import Image from 'next/image';
import { useEffect, useState } from 'react';

import { jobOutputs } from '@/components/job/job-outputs';
import { Dialog } from '@/components/ui/dialog';
import { EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { api } from '@/lib/api/client';
import type { GenerationJob, Page } from '@/lib/api/types';

/** Only what the form needs to render a thumbnail and send an id back. */
export interface ExistingAssetPick {
  id: string;
  url: string;
}

/**
 * Lets an edit form point a single image slot at an asset the user already
 * generated. There is no general asset-library endpoint, so this reuses the
 * user's own succeeded text-to-image/image-to-image job outputs.
 *
 * Copy is passed in so character and scene libraries keep their own i18n
 * keys. Modeled on `use-resource.ts`: "loading" is derived from the absence
 * of a result rather than a `setLoading(true)` at the top of the effect, so
 * the fetch only ever runs once per mount (cached across repeated slot
 * picks) and no setState happens synchronously in the effect body.
 */
export function ExistingAssetPickerDialog({
  open,
  onClose,
  onSelect,
  title,
  empty,
  error,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (asset: ExistingAssetPick) => void;
  title: string;
  empty: string;
  error: string;
}) {
  const [result, setResult] = useState<
    { status: 'ready'; assets: ExistingAssetPick[] } | { status: 'failed' } | null
  >(null);

  useEffect(() => {
    if (!open || result !== null) return;
    let cancelled = false;
    void api
      .get<Page<GenerationJob>>('/v1/generation-jobs?status=succeeded&limit=50')
      .then((page) => {
        if (cancelled) return;
        const items: ExistingAssetPick[] = [];
        for (const job of page.items) {
          if (job.operation !== 'text_to_image' && job.operation !== 'image_to_image') continue;
          const { urls, assetIds: ids } = jobOutputs(job);
          ids.forEach((id, index) => {
            const url = urls[index];
            if (url) items.push({ id, url });
          });
        }
        setResult({ status: 'ready', assets: items });
      })
      .catch(() => {
        if (!cancelled) setResult({ status: 'failed' });
      });
    return () => {
      cancelled = true;
    };
  }, [open, result]);

  const loading = open && result === null;
  const failed = result?.status === 'failed';
  const assets = result?.status === 'ready' ? result.assets : [];

  return (
    <Dialog open={open} onClose={onClose} title={title} size="lg">
      {loading ? (
        <div className="flex justify-center py-10">
          <Spinner className="size-5" />
        </div>
      ) : failed ? (
        <ErrorNotice title={error} />
      ) : assets.length === 0 ? (
        <EmptyState title={empty} />
      ) : (
        <div className="grid grid-cols-4 gap-2 sm:grid-cols-5">
          {assets.map((asset) => (
            <button
              key={asset.id}
              type="button"
              onClick={() => onSelect(asset)}
              className="relative aspect-square overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft"
            >
              <Image src={asset.url} alt="" fill sizes="120px" className="object-cover" />
            </button>
          ))}
        </div>
      )}
    </Dialog>
  );
}
