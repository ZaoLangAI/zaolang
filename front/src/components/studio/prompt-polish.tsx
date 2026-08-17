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
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { PromptEnhancePayload, PromptEnhanceResult } from '@/lib/api/types';

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
}: {
  /** Different per studio: shortform's is feature-flag gated, the generation studio's is not. */
  endpoint: string;
  prompt: string;
  context?: PromptPolishContext;
  onAccept: (prompt: string) => void;
  className?: string;
}) {
  const t = useTranslations('promptPolish');
  const tStates = useTranslations('states');
  const { requireAuth } = useSession();

  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<PromptEnhanceResult | null>(null);
  const [instruction, setInstruction] = useState('');

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
          };
          const result = await api.post<PromptEnhanceResult>(endpoint, body);
          setSuggestion(result);
          setInstruction('');
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
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
