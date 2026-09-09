'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import {
  DIRECTIONS,
  type Direction,
  PromptPolishPanel,
  VIDEO_ONLY_DIRECTIONS,
} from '@/components/studio/prompt-polish-panel';
import {
  hasMissingRequiredAnswer,
  type QuestionAnswer,
} from '@/components/studio/question-field';
import { Button } from '@/components/ui/button';
import { IconSparkle } from '@/components/ui/icons';
import { ApiError } from '@/lib/api/errors';
import type {
  PromptEnhancePayload,
  PromptEnhanceResult,
  PromptEnhanceScriptSegment,
} from '@/lib/api/types';
import { streamPost } from '@/lib/sse-post';

/** What the studio already knows, forwarded so the advice fits the job. */
export interface PromptPolishContext {
  operation?: PromptEnhancePayload['operation'];
  aspectRatio?: string;
  durationSeconds?: number;
  qualityTier?: PromptEnhancePayload['quality_tier'];
  styleHint?: string;
  hasReference?: boolean;
  /** Only meaningful for an image job — routes the polish to that kind's
   * dedicated agent (`character`/`scene`/`cover`); omitted or `general`
   * behaves like before. `ShortformStudio` never sets this. */
  assetKind?: PromptEnhancePayload['asset_kind'];
  /** The video-side equivalent of `assetKind` — routes the polish to that
   * kind's dedicated agent (`character_action`/`transition_video`/
   * `cover_video`); omitted or `general` behaves like before. A caller
   * sets at most one of `assetKind`/`videoAssetKind`. */
  videoAssetKind?: PromptEnhancePayload['video_asset_kind'];
  /** Clip studio: polish the prompt and these colour blocks together. */
  scriptSegment?: PromptEnhanceScriptSegment;
}

/**
 * The "AI 润色" control used by `PromptField`, in turn used by
 * `ImageGenerationStudio`/`VideoGenerationStudio` through `PromptComposer`
 * ("说说你想怎么改" card) — audio never sets `polishContext` below, so this
 * never renders there.
 *
 * A button that asks the copy agent to diagnose the description dimension
 * by dimension, then an inline result panel (`PromptPolishPanel`) that
 * unfolds directly inside that same card, right under the button — not a
 * separate overlay — so the suggestion reads as part of the composer rather
 * than a popup elsewhere on the page. The author can keep editing the field
 * while it's open, iterate on the suggestion, or autofill it; closing is
 * only ever the panel's own close button, never a side effect of accepting
 * a suggestion.
 */
export function PromptPolish({
  endpoint,
  prompt,
  context,
  onAccept,
  className,
  closeSignal,
  onBlockedChange,
  onPendingChange,
}: {
  /** Different per studio: shortform's is feature-flag gated, the generation studio's is not. */
  endpoint: string;
  prompt: string;
  context?: PromptPolishContext;
  onAccept: (prompt: string, segment?: PromptEnhanceScriptSegment) => void;
  className?: string;
  /** Raised while the coach is still waiting on a required answer. The scene
   * studio blocks submission on it — a plate generated from a description
   * the coach has already flagged as underspecified is the failure this
   * whole flow exists to stop. Never fires before the author polishes at
   * all, so a straight-to-generate author is untouched. */
  onBlockedChange?: (blocked: boolean) => void;
  /** Raised while a polish stream is in flight — the video / clip studio
   * locks "生成我的版本" on it so a half-finished suggestion cannot be
   * submitted as the next version. Image ignores this. */
  onPendingChange?: (pending: boolean) => void;
  /** Bumping this (e.g. on every "生成我的版本" click) closes the drawer if
   * it happens to be open — the caller owns the counter, this component just
   * reacts to it changing. `undefined` (the default) never closes it. */
  closeSignal?: number;
}) {
  const t = useTranslations('promptPolish');
  const tStates = useTranslations('states');
  const { requireAuth } = useSession();

  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<PromptEnhanceResult | null>(null);
  const [thinking, setThinking] = useState('');
  const [instruction, setInstruction] = useState('');
  const [answers, setAnswers] = useState<Record<string, QuestionAnswer>>({});

  // Derived during render rather than pushed from an effect: the parent only
  // needs the latest value, and an effect would report it one paint late.
  const questions = suggestion?.questions ?? [];
  const blocked = hasMissingRequiredAnswer(questions, answers);
  const [lastBlocked, setLastBlocked] = useState(blocked);
  if (blocked !== lastBlocked) {
    setLastBlocked(blocked);
    onBlockedChange?.(blocked);
  }

  // Adjusted during render rather than in an effect (same pattern as
  // `ImageGenerationStudio`'s own resumed-job handling) — closing on a
  // `closeSignal` change is a pure reaction to a prop, not a side effect to
  // synchronize with anything external. State, not a ref: refs can't be read
  // or written during render.
  const [lastCloseSignal, setLastCloseSignal] = useState(closeSignal);
  if (closeSignal !== undefined && closeSignal !== lastCloseSignal) {
    setLastCloseSignal(closeSignal);
    if (open) setOpen(false);
  }

  const onPendingChangeRef = useRef(onPendingChange);
  onPendingChangeRef.current = onPendingChange;
  // A parent that locked submit on `pending` must unlock if this unmounts
  // mid-stream (navigating away, swapping studios) — otherwise the button
  // stays stuck. The in-flight `request()` also reports true/false itself.
  useEffect(() => {
    return () => onPendingChangeRef.current?.(false);
  }, []);

  const isVideo = !context?.operation || context.operation.endsWith('_video');
  const directions = DIRECTIONS.filter(
    (direction) => isVideo || !VIDEO_ONLY_DIRECTIONS.includes(direction),
  );

  /**
   * One round. `base` is the original field for the first pass and the
   * accepted-so-far suggestion when iterating, so a direction refines the
   * previous round instead of restarting from the author's first draft.
   */
  const request = (
    base: string,
    extra?: {
      direction?: Direction;
      instruction?: string;
      scriptSegment?: PromptEnhanceScriptSegment;
      questionAnswers?: Record<string, QuestionAnswer>;
    },
  ) =>
    requireAuth({
      label: t('button'),
      run: async () => {
        setOpen(true);
        setPending(true);
        onPendingChangeRef.current?.(true);
        setError(null);
        setThinking('');
        try {
          const body: PromptEnhancePayload = {
            prompt: base.trim(),
            operation: context?.operation,
            aspect_ratio: context?.aspectRatio,
            duration_seconds: context?.durationSeconds,
            quality_tier: context?.qualityTier,
            style_hint: context?.styleHint ?? '',
            has_reference: context?.hasReference ?? false,
            direction: extra?.direction,
            instruction: extra?.instruction ?? '',
            asset_kind: context?.assetKind,
            video_asset_kind: context?.videoAssetKind,
            script_segment: extra?.scriptSegment ?? context?.scriptSegment,
            question_answers: extra?.questionAnswers,
          };
          let result: PromptEnhanceResult | null = null;
          for await (const frame of streamPost(endpoint, body)) {
            if (frame.event === 'thinking' && typeof frame.data.text === 'string') {
              setThinking((current) => current + frame.data.text);
            } else if (frame.event === 'complete') {
              result = frame.data as unknown as PromptEnhanceResult;
            } else if (frame.event === 'error') {
              const message =
                typeof frame.data.message === 'string' ? frame.data.message : tStates('errorHint');
              throw new Error(message);
            }
          }
          if (!result) throw new Error(tStates('errorHint'));
          setSuggestion(result);
          setInstruction('');
          setThinking('');
          // The answers just sent are folded into the new text; keeping them
          // around would re-send them as "still unanswered" state on the next
          // round and confuse the submit gate.
          if (extra?.questionAnswers) setAnswers({});
        } catch (caught) {
          setError(
            caught instanceof ApiError
              ? caught.message
              : caught instanceof Error
                ? caught.message
                : tStates('errorHint'),
          );
        } finally {
          setPending(false);
          onPendingChangeRef.current?.(false);
        }
      },
    });

  return (
    <div className={className}>
      <Button
        size="sm"
        variant="secondary"
        icon={<IconSparkle className="size-4" />}
        disabled={prompt.trim().length === 0 || pending}
        loading={pending}
        onClick={() => request(prompt)}
      >
        {pending ? t('buttonPending') : t('button')}
      </Button>

      <PromptPolishPanel
        open={open}
        onClose={() => setOpen(false)}
        pending={pending}
        thinking={thinking}
        error={error}
        suggestion={suggestion}
        instruction={instruction}
        onInstructionChange={setInstruction}
        directions={directions}
        onDirection={(direction) =>
          suggestion &&
          request(suggestion.prompt, {
            direction,
            scriptSegment: suggestion.script_segment,
          })
        }
        onRefine={() =>
          suggestion &&
          instruction.trim() &&
          request(suggestion.prompt, {
            instruction: instruction.trim(),
            scriptSegment: suggestion.script_segment,
          })
        }
        onAutofill={() => suggestion && onAccept(suggestion.prompt, suggestion.script_segment)}
        answers={answers}
        onAnswerChange={(id, value) => setAnswers((current) => ({ ...current, [id]: value }))}
        onAnswerSubmit={() =>
          suggestion &&
          request(suggestion.prompt, {
            questionAnswers: answers,
            scriptSegment: suggestion.script_segment,
          })
        }
      />
    </div>
  );
}
