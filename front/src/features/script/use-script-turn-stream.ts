'use client';

import { useCallback, useRef, useState } from 'react';

import * as scriptApi from './api';
import type { ScriptDocument, ScriptTurnCompleteEvent } from './api';

export interface ScriptTurnStreamState {
  streaming: boolean;
  liveText: string;
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
  const [state, setState] = useState<ScriptTurnStreamState>({
    streaming: false,
    liveText: '',
    error: null,
  });
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(
    async (request: TurnRequest, onComplete: (result: ScriptTurnCompleteEvent) => void) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setState({ streaming: true, liveText: '', error: null });

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
          } else if (event.event === 'error') {
            setState({ streaming: false, liveText: '', error: event.data.message });
            return;
          } else if (event.event === 'complete') {
            setState({ streaming: false, liveText: '', error: null });
            onComplete(event.data);
            return;
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({
          streaming: false,
          liveText: '',
          error: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [],
  );

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    setState({ streaming: false, liveText: '', error: null });
  }, []);

  return { ...state, run, cancel };
}
