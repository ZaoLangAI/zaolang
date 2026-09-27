import { api } from '@/lib/api/client';

import type { CanvasNode } from './api';
import { streamPost } from '@/lib/sse-post';

/**
 * The canvas Agent's client surface.
 *
 * Kept out of `api.ts` because the planning turn is the only POST-initiated
 * stream on the canvas and drags `sse-post` in with it; the graph API is a
 * plain REST client that every card path already loads.
 */

export type CanvasAgentRunStatus =
  | 'planning'
  | 'awaiting_confirm'
  | 'submitting'
  | 'running'
  | 'succeeded'
  /** Some tasks landed and some did not — the user has results worth keeping,
   * so this is deliberately not reported as a failure. */
  | 'partial'
  | 'failed'
  | 'cancelled';

export type CanvasAgentTaskStatus =
  | 'planned'
  | 'submitted'
  | 'running'
  | 'landed'
  | 'failed'
  | 'cancelled'
  /** Refused before submission — a reference the planner invented, or a canvas
   * with no room left. Nothing was charged for it. */
  | 'skipped';

export interface CanvasAgentTask {
  id: string;
  ordinal: number;
  operation: string;
  quality_tier: string;
  prompt: string;
  status: CanvasAgentTaskStatus;
  generation_job_id: string | null;
  /** Reserved at plan time, so the slot can be shown before it fills. */
  drop: { x: number; y: number };
  result_node_id: string | null;
  failure_message: string | null;
}

export interface CanvasAgentRun {
  id: string;
  canvas_id: string;
  status: CanvasAgentRunStatus;
  /** `agent` for a planned run, `workflow` for one expanded from a skill's
   * template. A field rather than an inference: both kinds go through the
   * same confirm / cancel / landing path, so the origin is the only thing
   * that tells them apart. */
  origin: 'agent' | 'workflow';
  goal: string;
  summary: string;
  agent_node_id: string | null;
  context_node_ids: string[];
  quoted_credits: number;
  model: string | null;
  failure_code: string | null;
  failure_message: string | null;
  tasks: CanvasAgentTask[];
  created_at: string;
  updated_at: string;
}

export interface CanvasAgentPlanInput {
  agentNodeId: string;
  goal: string;
  qualityTier?: string;
  maxTasks?: number;
  maxCredits?: number | null;
}

/**
 * Stream a planning turn.
 *
 * Yields the same envelope as script turns and the editor planner
 * (`thinking` / `delta` / `complete` / `error`), so the panel can show the
 * model working rather than a spinner. The run is written server-side only
 * once the stream drains — an abandoned plan leaves no row and costs nothing.
 */
export function streamCanvasAgentPlan(
  canvasId: string,
  input: CanvasAgentPlanInput,
  signal?: AbortSignal,
) {
  return streamPost(
    `/v1/canvas-projects/${canvasId}/agent-runs`,
    {
      agent_node_id: input.agentNodeId,
      goal: input.goal,
      ...(input.qualityTier ? { quality_tier: input.qualityTier } : {}),
      ...(input.maxTasks ? { max_tasks: input.maxTasks } : {}),
      ...(input.maxCredits != null ? { max_credits: input.maxCredits } : {}),
    },
    signal,
  );
}

/**
 * Spend the credits and submit the planned jobs.
 *
 * `idempotencyKey` is one per confirm *attempt*, reused on retry: a retry after
 * a timeout then gets the original answer instead of an "already submitted"
 * error for credits that were in fact spent. Callers hold it via
 * `useConfirmCanvasAgentRun`.
 */
export function confirmCanvasAgentRun(
  runId: string,
  idempotencyKey: string,
): Promise<CanvasAgentRun> {
  return api.post<CanvasAgentRun>(`/v1/canvas-agent-runs/${runId}/confirm`, {}, { idempotencyKey });
}

export function cancelCanvasAgentRun(runId: string): Promise<CanvasAgentRun> {
  return api.post<CanvasAgentRun>(`/v1/canvas-agent-runs/${runId}/cancel`, {});
}

export function getCanvasAgentRun(runId: string): Promise<CanvasAgentRun> {
  return api.get<CanvasAgentRun>(`/v1/canvas-agent-runs/${runId}`);
}

export function listCanvasAgentRuns(canvasId: string): Promise<CanvasAgentRun[]> {
  return api.get<CanvasAgentRun[]>(`/v1/canvas-projects/${canvasId}/agent-runs`);
}

/**
 * Put a landed result back on the canvas.
 *
 * Only for a card the user deleted after it landed — results place themselves
 * (see the completion hook). Refused server-side if the card is still there,
 * so a double-tap cannot leave two copies of one generation.
 */
export function restoreCanvasTaskCard(taskId: string): Promise<CanvasNode> {
  return api.post<CanvasNode>(`/v1/canvas-agent-tasks/${taskId}/restore-card`, {});
}

/**
 * Expand a creation workflow into a priced, unconfirmed run.
 *
 * Plain JSON, not a stream: a workflow's plan comes from its own template, so
 * there is no model call to watch. What comes back is the same
 * `CanvasAgentRun` the planner produces, and goes on through the same
 * `confirmCanvasAgentRun` — a workflow does not get its own submit path.
 */
export function startCanvasWorkflowRun(
  canvasId: string,
  input: {
    skillId: string;
    nodeId: string;
    answers: Record<string, string | string[]>;
    qualityTier?: string;
  },
): Promise<CanvasAgentRun> {
  return api.post<CanvasAgentRun>(`/v1/canvas-projects/${canvasId}/workflow-runs`, {
    skill_id: input.skillId,
    node_id: input.nodeId,
    answers: input.answers,
    ...(input.qualityTier ? { quality_tier: input.qualityTier } : {}),
  });
}
