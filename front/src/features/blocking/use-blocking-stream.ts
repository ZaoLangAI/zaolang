'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useRef, useState } from 'react';

import type { ScriptDocument } from '@/features/script/api';

import * as blockingApi from './api';
import type { BlockingPhase, BlockingTurnCompleteEvent } from './api';

export interface BlockingStreamState {
  streaming: boolean;
  phase: BlockingPhase | null;
  /** Raw reply text of the *current* phase only — each phase is its own
   * model call with its own summary + fenced JSON. */
  liveText: string;
  liveThinking: string;
  error: string | null;
}

type Request =
  | { kind: 'turn'; episodeId: string; message: string; currentScript: ScriptDocument }
  | { kind: 'rebuild'; episodeId: string };

const IDLE: BlockingStreamState = {
  streaming: false,
  phase: null,
  liveText: '',
  liveThinking: '',
  error: null,
};

/** Drives one streamed 白膜 turn or rebuild — the `use-script-turn-stream`
 * pattern plus the `phase` channel. */
export function useBlockingStream() {
  const t = useTranslations('blockingStudio');
  const [state, setState] = useState<BlockingStreamState>(IDLE);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(
    async (request: Request, onComplete: (result: BlockingTurnCompleteEvent) => void) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setState({ ...IDLE, streaming: true });
      try {
        const events =
          request.kind === 'turn'
            ? blockingApi.sendBlockingTurn(
                request.episodeId,
                { message: request.message, currentScript: request.currentScript },
                controller.signal,
              )
            : blockingApi.rebuildBlocking(request.episodeId, controller.signal);
        for await (const event of events) {
          if (controller.signal.aborted) return;
          if (event.event === 'phase') {
            setState((current) => ({ ...current, phase: event.data.name, liveText: '' }));
          } else if (event.event === 'delta') {
            setState((current) => ({ ...current, liveText: current.liveText + event.data.text }));
          } else if (event.event === 'thinking') {
            setState((current) => ({
              ...current,
              liveThinking: current.liveThinking + event.data.text,
            }));
          } else if (event.event === 'error') {
            setState({ ...IDLE, error: event.data.message });
            return;
          } else if (event.event === 'complete') {
            setState(IDLE);
            onComplete(event.data);
            return;
          }
        }
        if (!controller.signal.aborted) setState({ ...IDLE, error: t('streamEnded') });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({ ...IDLE, error: error instanceof Error ? error.message : String(error) });
      }
    },
    [t],
  );

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    setState(IDLE);
  }, []);

  return { ...state, run, cancel };
}
