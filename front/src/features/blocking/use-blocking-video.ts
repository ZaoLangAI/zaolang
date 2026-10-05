'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { pollJob, submitJob } from '@/features/script/use-script-batch';
import { isApiError } from '@/lib/api/errors';
import type { QualityTier } from '@/lib/api/types';
import { uploadFile } from '@/lib/upload';

import {
  BrowserCannotEncodeError,
  renderSegmentClip,
  segmentClipName,
} from './export/render-segment';
import type { BlockingDocument } from './types';
import type { SegmentVideoPlan } from './video-plan';

export type SegmentVideoStatus =
  'queued' | 'rendering' | 'uploading' | 'submitting' | 'running' | 'succeeded' | 'failed';

export interface SegmentVideoItem {
  key: string;
  heading: string;
  status: SegmentVideoStatus;
  /** 0–1 while rendering the reference clip. */
  progress: number;
  draftId?: string;
  jobId?: string;
  error?: string;
}

/** `SegmentVideoItem.error` when this browser can neither encode nor
 * record video; the panel shows a translated explanation instead. */
export const BROWSER_CANNOT_ENCODE = 'browser_cannot_encode_video';

export interface SegmentVideoParams {
  qualityTier: QualityTier;
  resolution: '480p' | '720p' | '1080p' | '2K';
}

/**
 * 白膜 → video, one segment at a time: render the segment's blockout to a
 * clip in the browser (MP4, or WebM where only recording is available), upload it as a private generation reference, then
 * submit a `text_to_video` job with that clip as the *motion guide* plus the
 * cast's character assets and the scene asset as appearance references.
 *
 * Drafts carry `link_episode_id`/`link_breakpoint_key` exactly as the script
 * page's batch does, so each result binds to the same segment chip there.
 * Sequential on purpose: rendering holds a WebGL context and the encoder,
 * and a failed segment stops the queue rather than spending more credits.
 */
export function useBlockingVideo(episodeId: string) {
  const [items, setItems] = useState<SegmentVideoItem[]>([]);
  const [running, setRunning] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const patch = useCallback((key: string, next: Partial<SegmentVideoItem>) => {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...next } : item)));
  }, []);

  const start = useCallback(
    async (
      document: BlockingDocument,
      plans: SegmentVideoPlan[],
      params: SegmentVideoParams,
      unitCreditsByKey: Record<string, number>,
    ) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      const signal = controller.signal;
      setRunning(true);
      setItems(
        plans.map((plan) => ({
          key: plan.key,
          heading: plan.heading,
          status: 'queued',
          progress: 0,
        })),
      );

      for (const plan of plans) {
        if (signal.aborted) break;
        try {
          patch(plan.key, { status: 'rendering', progress: 0 });
          const clip = await renderSegmentClip(document, plan.key, {
            signal,
            onProgress: ({ fraction }) => patch(plan.key, { progress: fraction }),
          });
          patch(plan.key, { status: 'uploading', progress: 1 });
          const asset = await uploadFile(
            new File([clip.blob], segmentClipName(plan.key, clip.extension), {
              type: clip.mimeType,
            }),
            'generation_reference',
          );
          patch(plan.key, { status: 'submitting' });
          const job = await submitJob({
            operation: 'text_to_video',
            qualityTier: params.qualityTier,
            prompt: plan.prompt,
            aspectRatio: document.aspect_ratio,
            durationSeconds: plan.durationSeconds,
            draftTitle: plan.heading,
            referenceAssetIds: [asset.id],
            characterIds: plan.characterIds,
            sceneIds: plan.sceneId ? [plan.sceneId] : [],
            videoOptions: {
              resolution: params.resolution,
              reference_mode: 'input_references',
              reference_video_role: 'motion_guide',
            },
            linkEpisodeId: episodeId,
            linkBreakpointKey: plan.key,
            assetPresets: plan.referenceCamera ?? undefined,
            maxCredits: unitCreditsByKey[plan.key] ?? 0,
          });
          patch(plan.key, {
            status: 'running',
            jobId: job.id,
            draftId: job.draft_id ?? undefined,
          });
          const finished = await pollJob(job.id, signal);
          if (finished.status !== 'succeeded') {
            patch(plan.key, {
              status: 'failed',
              error: finished.failure_message || finished.status,
            });
            break;
          }
          patch(plan.key, {
            status: 'succeeded',
            draftId: finished.draft_id ?? job.draft_id ?? undefined,
          });
        } catch (error) {
          if (signal.aborted) break;
          patch(plan.key, {
            status: 'failed',
            error: isApiError(error)
              ? error.message
              : error instanceof BrowserCannotEncodeError
                ? BROWSER_CANNOT_ENCODE
                : error instanceof Error
                  ? error.message
                  : 'failed',
          });
          break;
        }
      }
      if (!signal.aborted) setRunning(false);
    },
    [episodeId, patch],
  );

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    setRunning(false);
  }, []);

  return { items, running, start, cancel };
}
