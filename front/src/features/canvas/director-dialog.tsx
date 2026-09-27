'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/primitives';
import { uploadFile, type Asset } from '@/lib/upload';

import type { CanvasSnapshot } from './api';
import { applyCameraPrompt } from './canvas-camera';
import { CameraControl, DEFAULT_CAMERA_CONTROL } from './camera-control';
import { composeShot, describeFraming, type CharacterPlacement } from './director-capture';
import { PanoramaViewer, type PanoramaHandle } from './panorama-viewer';

/**
 * The director suite: stand inside a 360° environment, frame a shot, and take
 * it away as a still plus the words describing how it was framed.
 *
 * Why a still and a sentence, and not camera data: nothing this platform
 * routes to accepts a camera position. The video models take a prompt, a first
 * and last frame, and reference media — nothing else (see the
 * `zaolang-agent-gateway` providers reference, AiHubMix and DMXAPI). So a
 * framed view has to leave here as a picture and as prompt text, which is
 * exactly what upstream's own director does.
 *
 * The panorama is uploaded, not generated: `_IMAGE_SIZE_BY_ASPECT` has no 2:1
 * entry and silently returns a square, so text-to-panorama would quietly hand
 * back something that is not a panorama at all.
 */
export function DirectorDialog({
  open,
  onClose,
  snapshot,
  onCaptured,
}: {
  open: boolean;
  onClose: () => void;
  snapshot: CanvasSnapshot;
  /** The finished still plus the prompt describing how it was framed. */
  onCaptured: (asset: Asset, framingPrompt: string) => void;
}) {
  const t = useTranslations('canvas');
  const viewerRef = useRef<PanoramaHandle | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [panorama, setPanorama] = useState<{ url: string } | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [camera, setCamera] = useState({ ...DEFAULT_CAMERA_CONTROL, enabled: true });
  const [placements, setPlacements] = useState<CharacterPlacement[]>([]);
  const [dragging, setDragging] = useState<string | null>(null);

  const loadPanorama = (file: File) => {
    // A local object URL, not an upload: the environment is scaffolding for
    // framing the shot. Only the finished still is worth storing.
    setPanorama({ url: URL.createObjectURL(file) });
    setReady(false);
  };

  const addCharacter = (skillId: string, url: string) => {
    setPlacements((current) => [
      ...current,
      { id: `${skillId}-${current.length}`, skillId, url, x: 0.5, y: 0.6, scale: 0.5 },
    ]);
  };

  const onStagePointerMove = (event: React.PointerEvent) => {
    if (!dragging) return;
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    setPlacements((current) =>
      current.map((placement) =>
        placement.id === dragging
          ? { ...placement, x: Math.min(1, Math.max(0, x)), y: Math.min(1, Math.max(0, y)) }
          : placement,
      ),
    );
  };

  const capture = useCallback(() => {
    const canvas = viewerRef.current?.captureCanvas();
    const position = viewerRef.current?.readPosition();
    if (!canvas) return;
    setBusy(true);
    void composeShot(canvas, placements)
      .then((blob) =>
        uploadFile(
          new File([blob], 'director-shot.png', { type: 'image/png' }),
          'generation_reference',
        ),
      )
      .then((asset) => {
        // Framing and glass together: where the camera points, then what it is
        // looking through. Both only ever reach a model as words.
        const framing = position ? describeFraming(position) : '';
        onCaptured(asset, applyCameraPrompt(framing, camera));
        onClose();
      })
      .finally(() => setBusy(false));
  }, [camera, onCaptured, onClose, placements]);

  const characters = snapshot.skills.filter((skill) => skill.thumbnail_url);

  return (
    <Dialog open={open} onClose={onClose} title={t('directorTitle')} size="lg">
      <div className="flex gap-4">
        <div className="min-w-0 flex-1 space-y-2">
          <div
            ref={stageRef}
            data-testid="director-stage"
            className="relative aspect-video w-full overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft"
            onPointerMove={onStagePointerMove}
            onPointerUp={() => setDragging(null)}
            onPointerLeave={() => setDragging(null)}
          >
            {panorama ? (
              <PanoramaViewer src={panorama.url} handleRef={viewerRef} onReady={setReady} />
            ) : (
              <div className="grid h-full place-items-center p-6">
                <EmptyState title={t('directorNoPanorama')} description={t('directorUploadHint')} />
              </div>
            )}
            {placements.map((placement) => (
              // A cut-out sits over the viewer rather than in the 3D scene:
              // characters here are the platform's existing 2D reference
              // images, and there is no rigged 3D model to place.
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                key={placement.id}
                src={placement.url}
                alt=""
                draggable={false}
                onPointerDown={() => setDragging(placement.id)}
                style={{
                  left: `${placement.x * 100}%`,
                  top: `${placement.y * 100}%`,
                  height: `${placement.scale * 100}%`,
                  transform: 'translate(-50%, -50%)',
                }}
                className="absolute cursor-move select-none object-contain drop-shadow-lg"
              />
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex">
              <span className="sr-only">{t('directorPanoramaFile')}</span>
              <input
                type="file"
                accept="image/*"
                className="sr-only"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) loadPanorama(file);
                  event.target.value = '';
                }}
              />
              <span className="inline-flex h-8 cursor-pointer items-center rounded-[var(--radius-sm)] border border-border px-3 text-sm transition-colors hover:bg-surface-soft">
                {t('directorPanoramaFile')}
              </span>
            </label>
            <Button size="sm" onClick={capture} disabled={!ready || busy} loading={busy}>
              {t('directorCapture')}
            </Button>
            <p className="text-[11px] text-muted">{t('directorPanoramaNote')}</p>
          </div>
        </div>

        <aside className="w-64 shrink-0 space-y-3 overflow-y-auto">
          <div>
            <p className="mb-1.5 text-xs text-muted">{t('directorCharacters')}</p>
            {characters.length === 0 ? (
              <p className="text-[11px] text-muted">{t('directorNoCharacters')}</p>
            ) : (
              <ul className="grid grid-cols-3 gap-1.5">
                {characters.map((skill) => (
                  <li key={skill.id}>
                    <button
                      type="button"
                      title={skill.title}
                      onClick={() => addCharacter(skill.id, skill.thumbnail_url!)}
                      className="block w-full overflow-hidden rounded-[var(--radius-sm)] border border-border transition-colors hover:border-primary"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={skill.thumbnail_url!}
                        alt={skill.title}
                        className="aspect-square w-full object-cover"
                      />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {placements.length > 0 ? (
              <Button
                size="sm"
                variant="ghost"
                className="mt-1.5"
                onClick={() => setPlacements([])}
              >
                {t('directorClearCharacters')}
              </Button>
            ) : null}
          </div>
          <CameraControl value={camera} onChange={setCamera} />
        </aside>
      </div>
    </Dialog>
  );
}
