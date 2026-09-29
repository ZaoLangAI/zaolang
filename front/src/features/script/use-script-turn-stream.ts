'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useRef, useState } from 'react';

import * as scriptApi from './api';
import type { ScriptDocument, ScriptTurnCompleteEvent } from './api';

export interface ScriptTurnStreamState {
  streaming: boolean;
  liveText: string;
  /** The model's live reasoning trace for the in-flight turn, accumulated
   * from `event: thinking` frames — a separate channel from `liveText`. */
  liveThinking: string;
  error: string | null;
}

type TurnRequest =
  | { kind: 'create'; title: string; idea: string; referencedSkillIds: string[] }
  | {
      kind: 'turn';
      episodeId: string;
      message: string;
      referencedSkillIds: string[];
      currentScript: ScriptDocument;
    };

/**
 * Drives one streamed script turn (first draft or a revision) and exposes
 * the live text as it types itself out. `liveText` holds the model's raw
 * reply (a short summary followed by a fenced script document) only while
 * `streaming` is true — once `complete` arrives the caller gets the parsed,
 * sanitized result via `onComplete` and `liveText` resets, because only the
 * final structured script and its clean summary are ever kept on screen.
 */
export function useScriptTurnStream() {
  const t = useTranslations('scriptStudio');
  const [state, setState] = useState<ScriptTurnStreamState>({
    streaming: false,
    liveText: '',
    liveThinking: '',
    error: null,
  });
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(
    async (request: TurnRequest, onComplete: (result: ScriptTurnCompleteEvent) => void) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setState({ streaming: true, liveText: '', liveThinking: '', error: null });

      try {
        const events =
          request.kind === 'create'
            ? scriptApi.createScript(
                {
                  title: request.title,
                  idea: request.idea,
                  referencedSkillIds: request.referencedSkillIds,
                },
                controller.signal,
              )
            : scriptApi.sendTurn(
                request.episodeId,
                {
                  message: request.message,
                  referencedSkillIds: request.referencedSkillIds,
                  currentScript: request.currentScript,
                },
                controller.signal,
              );

        for await (const event of events) {
          if (controller.signal.aborted) return;
          if (event.event === 'delta') {
            setState((current) => ({ ...current, liveText: current.liveText + event.data.text }));
          } else if (event.event === 'thinking') {
            setState((current) => ({
              ...current,
              liveThinking: current.liveThinking + event.data.text,
            }));
          } else if (event.event === 'error') {
            setState({
              streaming: false,
              liveText: '',
              liveThinking: '',
              error: event.data.message,
            });
            return;
          } else if (event.event === 'complete') {
            setState({ streaming: false, liveText: '', liveThinking: '', error: null });
            onComplete(event.data);
            return;
          }
        }
        // The body ended without a `complete`/`error` frame — stop
        // spinning rather than leave `streaming` stuck forever; there is
        // no partial turn to show, so `liveText`/`liveThinking` are
        // dropped the same way a `complete` frame would drop them. Unlike
        // a first draft's empty-shell recovery UI, a revision turn always
        // has a prior script to fall back to, so this surfaces as an
        // ordinary error instead.
        if (!controller.signal.aborted) {
          setState({
            streaming: false,
            liveText: '',
            liveThinking: '',
            error: t('turnStreamEndedWithoutResult'),
          });
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({
          streaming: false,
          liveText: '',
          liveThinking: '',
          error: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [t],
  );

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    setState({ streaming: false, liveText: '', liveThinking: '', error: null });
  }, []);

  return { ...state, run, cancel };
}
