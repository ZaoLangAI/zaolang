'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import {
  DIRECTIONS,
  type Direction,
  PromptPolishDrawer,
  VIDEO_ONLY_DIRECTIONS,
} from '@/components/studio/prompt-polish-drawer';
import { Button } from '@/components/ui/button';
import { IconSparkle } from '@/components/ui/icons';
import { ApiError } from '@/lib/api/errors';
import type { PromptEnhancePayload, PromptEnhanceResult } from '@/lib/api/types';
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
}

/**
 * The "AI 润色" control shared by `PromptField` (used by
 * `ImageGenerationStudio`/`VideoGenerationStudio`) and `ShortformStudio`.
 *
 * Both surfaces show the same thing: a button that asks the copy agent to
 * diagnose the description dimension by dimension, then a non-modal bottom
 * drawer (`PromptPolishDrawer`) the author can keep open while continuing to
 * edit the field, iterate on the suggestion, or autofill it — closing is
 * only ever the drawer's own close button, never a side effect of accepting
 * a suggestion.
 */
export function PromptPolish({
  endpoint,
  prompt,
  context,
  onAccept,
  className,
  closeSignal,
}: {
  /** Different per studio: shortform's is feature-flag gated, the generation studio's is not. */
  endpoint: string;
  prompt: string;
  context?: PromptPolishContext;
  onAccept: (prompt: string) => void;
  className?: string;
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

  const isVideo = !context?.operation || context.operation.endsWith('_video');
  const directions = DIRECTIONS.filter(
    (direction) => isVideo || !VIDEO_ONLY_DIRECTIONS.includes(direction),
  );

  /**
   * One round. `base` is the original field for the first pass and the
   * accepted-so-far suggestion when iterating, so a direction refines the
   * previous round instead of restarting from the author's first draft.
   */
  const request = (base: string, extra?: { direction?: Direction; instruction?: string }) =>
    requireAuth({
      label: t('button'),
      run: async () => {
        setOpen(true);
        setPending(true);
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

      <PromptPolishDrawer
        open={open}
        onClose={() => setOpen(false)}
        pending={pending}
        thinking={thinking}
        error={error}
        suggestion={suggestion}
        instruction={instruction}
        onInstructionChange={setInstruction}
        directions={directions}
        onDirection={(direction) => suggestion && request(suggestion.prompt, { direction })}
        onRefine={() =>
          suggestion &&
          instruction.trim() &&
          request(suggestion.prompt, { instruction: instruction.trim() })
        }
        onAutofill={() => suggestion && onAccept(suggestion.prompt)}
      />
    </div>
  );
}
