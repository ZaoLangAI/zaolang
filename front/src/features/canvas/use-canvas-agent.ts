'use client';

import { useCallback, useRef, useState } from 'react';

import {
  cancelCanvasAgentRun,
  confirmCanvasAgentRun,
  streamCanvasAgentPlan,
  type CanvasAgentRun,
} from './agent-api';

/**
 * Drives one Agent card: plan, review, confirm.
 *
 * Plan and confirm are deliberately two steps. The plan comes back priced and
 * the run rests at `awaiting_confirm`, so the user sees what it will cost
 * before a credit moves — spending someone's balance without a confirming tap
 * is what generates refund tickets.
 */

export type AgentPhase = 'idle' | 'planning' | 'reviewing' | 'submitting' | 'done' | 'error';

export interface CanvasAgentState {
  phase: AgentPhase;
  /** The model's reasoning trace, shown while it works rather than a spinner. */
  thinking: string;
  run: CanvasAgentRun | null;
  error: string | null;
}

const IDLE: CanvasAgentState = { phase: 'idle', thinking: '', run: null, error: null };

export function useCanvasAgent(canvasId: string) {
  const [state, setState] = useState<CanvasAgentState>(IDLE);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(IDLE);
  }, []);

  const plan = useCallback(
    async (input: {
      agentNodeId: string;
      goal: string;
      qualityTier?: string;
      maxTasks?: number;
    }) => {
      // One planning turn at a time per card: a second would race the first
      // into the same `agent_node_id` and leave two runs claiming one card.
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setState({ phase: 'planning', thinking: '', run: null, error: null });

      try {
        for await (const event of streamCanvasAgentPlan(canvasId, input, controller.signal)) {
          if (event.event === 'thinking') {
            const text = typeof event.data.text === 'string' ? event.data.text : '';
            setState((current) => ({ ...current, thinking: current.thinking + text }));
          } else if (event.event === 'complete') {
            const run = event.data as unknown as CanvasAgentRun;
            setState({
              // A run that came back already failed (an empty plan, say) has
              // nothing to review, so it goes straight to the error phase
              // rather than offering a confirm the user cannot act on.
              phase: run.status === 'failed' ? 'error' : 'reviewing',
              thinking: '',
              run,
              error: run.failure_message,
            });
          } else if (event.event === 'error') {
            const message =
              typeof event.data.message === 'string' ? event.data.message : '规划失败';
            setState({ phase: 'error', thinking: '', run: null, error: message });
          }
          // `delta` frames are the raw JSON plan being assembled. Not shown:
          // the parsed result arrives in `complete` a moment later, and half a
          // JSON document on screen is noise, not progress.
        }
      } catch (cause) {
        if (controller.signal.aborted) return;
        setState({
          phase: 'error',
          thinking: '',
          run: null,
          error: cause instanceof Error ? cause.message : String(cause),
        });
      }
    },
    [canvasId],
  );

  const confirm = useCallback(async () => {
    const runId = state.run?.id;
    if (!runId) return;
    setState((current) => ({ ...current, phase: 'submitting', error: null }));
    try {
      const run = await confirmCanvasAgentRun(runId);
      setState((current) => ({ ...current, phase: 'done', run }));
    } catch (cause) {
      setState((current) => ({
        ...current,
        // Back to reviewing, not error: the plan is still valid and the user
        // can try again. Credits were not spent on a failed submit.
        phase: 'reviewing',
        error: cause instanceof Error ? cause.message : String(cause),
      }));
    }
  }, [state.run?.id]);

  const cancel = useCallback(async () => {
    const runId = state.run?.id;
    abortRef.current?.abort();
    if (!runId) {
      setState(IDLE);
      return;
    }
    try {
      const run = await cancelCanvasAgentRun(runId);
      setState((current) => ({ ...current, phase: 'done', run }));
    } catch {
      setState(IDLE);
    }
  }, [state.run?.id]);

  return { state, plan, confirm, cancel, reset };
}
