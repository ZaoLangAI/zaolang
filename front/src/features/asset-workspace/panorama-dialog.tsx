'use client';

import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import type { AssetGraphActions } from '@/components/asset-graph/use-asset-graph';
import { composeShot } from '@/components/media/panorama-capture';
import { PanoramaViewer, type PanoramaHandle } from '@/components/media/panorama-viewer';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { AssetEntry, AssetGenerateResponse, AssetVariant, CameraPose } from '@/lib/api/types';
import { uploadFile } from '@/lib/upload';

import { entryPose, poseKey } from './camera';
import { poseLabel } from './orbit-picker';
import { panoramaPose, REFINE_INSTRUCTION } from './panorama';

interface Cut {
  entry: AssetEntry;
  pose: CameraPose;
  /** The 精修 price (`…:adjust` dry run), once known. */
  credits?: number;
  sufficient?: boolean;
  refined?: boolean;
}

/**
 * Stand inside a scene variant's panorama and cut posed shots out of it
 * (AC-7). 「截取当前机位」 renders the current view (`composeShot`, no
 * overlays), uploads it and files it as a `shot` of the variant with the
 * view's pose snapped to the grid — a candidate when that pose slot already
 * holds an approved image. 「精修」 then redraws the cut without the
 * panorama's distortion via `…/entries/{id}:adjust` (a candidate version).
 */
export function PanoramaDialog({
  open,
  onClose,
  panorama,
  variant,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  panorama: AssetEntry;
  variant: AssetVariant;
  actions: AssetGraphActions;
}) {
  const t = useTranslations('assetWorkspace');
  const { notify } = useToast();
  const viewerRef = useRef<PanoramaHandle | null>(null);
  const [ready, setReady] = useState(false);
  const [live, setLive] = useState<CameraPose | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cuts, setCuts] = useState<Cut[]>([]);
  const refineKeys = useRef(new Map<string, string>());
  // Pinned for the dialog's lifetime: every graph refetch (polling, or the
  // refresh after a cut) signs a new URL, and a new `src` rebuilds the
  // viewer — losing where the person was looking.
  const [src] = useState(panorama.url);

  const readPose = (): CameraPose | null => {
    const position = viewerRef.current?.readPosition();
    return position ? panoramaPose(position) : null;
  };
  const track = () => setLive(readPose());

  const fail = (caught: unknown) => {
    const message = caught instanceof ApiError ? caught.message : t('genericError');
    setError(message);
  };

  const quoteRefine = (entry: AssetEntry) =>
    api
      .post<AssetGenerateResponse>(`${actions.base}/entries/${entry.id}:adjust`, {
        instruction: REFINE_INSTRUCTION,
        dry_run: true,
      })
      .then((quote) =>
        setCuts((list) =>
          list.map((cut) =>
            cut.entry.id === entry.id
              ? { ...cut, credits: quote.credits, sufficient: quote.sufficient }
              : cut,
          ),
        ),
      )
      .catch(fail);

  const capture = async () => {
    const canvas = viewerRef.current?.captureCanvas();
    const pose = readPose();
    if (!canvas || !pose) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await composeShot(canvas, []);
      const asset = await uploadFile(
        new File([blob], 'panorama-shot.png', { type: 'image/png' }),
        'generation_reference',
      );
      // A manual entry is approved at once; never displace the slot's
      // approved image — the cut waits as a candidate beside it instead.
      const taken = (variant.entries ?? []).some((e) => {
        const shown = e.entry_type === 'shot' && e.status === 'approved' ? entryPose(e) : null;
        return shown !== null && poseKey(shown) === poseKey(pose);
      });
      let entry = await api.post<AssetEntry>(
        `${actions.base}/${actions.segment}/${variant.id}/entries`,
        {
          asset_id: asset.id,
          entry_type: 'shot',
          camera: pose,
        },
      );
      if (taken) {
        entry = await api.patch<AssetEntry>(`${actions.base}/entries/${entry.id}`, {
          status: 'candidate',
        });
      }
      setCuts((list) => [{ entry, pose }, ...list]);
      notify(t('panorama.captured', { pose: poseLabel(t, pose) }), 'success');
      void quoteRefine(entry);
      await actions.refresh();
    } catch (caught) {
      fail(caught);
    } finally {
      setBusy(false);
    }
  };

  const refine = async (cut: Cut) => {
    const keys = refineKeys.current;
    const key = keys.get(cut.entry.id) ?? newIdempotencyKey();
    keys.set(cut.entry.id, key);
    setBusy(true);
    setError(null);
    try {
      await api.post(
        `${actions.base}/entries/${cut.entry.id}:adjust`,
        { instruction: REFINE_INSTRUCTION, dry_run: false },
        { idempotencyKey: key },
      );
      setCuts((list) =>
        list.map((item) => (item.entry.id === cut.entry.id ? { ...item, refined: true } : item)),
      );
      await actions.refresh();
    } catch (caught) {
      fail(caught);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('panorama.title', { variant: variant.name })}
      description={t('panorama.description')}
      size="xl"
    >
      <div className="flex flex-col gap-3">
        <div
          className="relative aspect-video w-full overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft"
          onPointerUp={track}
          onWheel={track}
          onKeyUp={track}
        >
          {src ? (
            <PanoramaViewer
              src={src}
              handleRef={viewerRef}
              onReady={(next) => {
                setReady(next);
                if (next) track();
              }}
            />
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void capture()} disabled={!ready || busy} loading={busy}>
            {t('panorama.capture')}
          </Button>
          <p className="text-xs text-muted" aria-live="polite">
            {live ? t('panorama.currentPose', { pose: poseLabel(t, live) }) : t('panorama.loading')}
          </p>
        </div>
        <p className="text-[11px] text-muted">{t('panorama.hint')}</p>

        {error ? <ErrorNotice title={error} /> : null}

        {cuts.length ? (
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label={t('panorama.cuts')}>
            {cuts.map((cut) => (
              <li key={cut.entry.id} className="flex flex-col gap-1">
                <div className="relative aspect-video overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
                  {cut.entry.url ? (
                    <Image src={cut.entry.url} alt="" fill sizes="240px" className="object-cover" />
                  ) : null}
                </div>
                <span className="truncate text-xs">
                  {poseLabel(t, cut.pose)}
                  {cut.entry.status === 'candidate' ? ` · ${t('status.candidate')}` : ''}
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy || cut.refined || cut.credits === undefined || !cut.sufficient}
                  onClick={() => void refine(cut)}
                >
                  {cut.refined
                    ? t('panorama.refining')
                    : cut.credits === undefined
                      ? t('generatePricing')
                      : t('panorama.refineFor', { credits: cut.credits })}
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Dialog>
  );
}
