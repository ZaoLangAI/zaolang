'use client';

import { PromptField, type PromptSkillMention } from '@/components/studio/prompt-field';
import type { PromptPolishContext } from '@/components/studio/prompt-polish';
import type { PromptEnhanceScriptSegment } from '@/lib/api/types';
import { IconSparkle } from '@/components/ui/icons';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';

/**
 * The richer "说说你想怎么改" composer card that sits directly beneath the
 * preview area (`GenerationStudioShell`'s `promptSlot`) instead of inside
 * the params aside/`Sheet` — all three studios (`ImageGenerationStudio`,
 * `VideoGenerationStudio`, `AudioGenerationStudio`) put their `PromptField`
 * here so the author writes right next to what they're looking at, and it
 * stays visible on every breakpoint rather than only after opening "调整参数".
 * Audio omits polish and `@` mention; it still applies skills from the
 * params-panel Select.
 *
 * Wraps `PromptField` rather than reimplementing it: the textarea's own
 * accessible label/counter/AI-润色 button/`@` mention menu are unchanged,
 * only the chrome and position around it are new. Deliberately has no
 * `overflow-hidden` on the card — `SkillMentionMenu` is absolutely
 * positioned against `PromptField`'s own container and would get clipped by
 * it.
 */
export function PromptComposer({
  prompt,
  onChange,
  polishContext,
  onPolishAccept,
  closePolishSignal,
  onPolishBlockedChange,
  onPolishPendingChange,
  skillMention,
  skillChips,
  unlockDialog,
  hint,
  tip,
  after,
}: {
  prompt: string;
  onChange: (value: string) => void;
  polishContext?: PromptPolishContext;
  onPolishAccept?: (prompt: string, segment?: PromptEnhanceScriptSegment) => void;
  closePolishSignal?: number;
  /** Forwarded to `PromptField` -> `PromptPolish`. */
  onPolishBlockedChange?: (blocked: boolean) => void;
  /** Forwarded to `PromptField` -> `PromptPolish` — video / clip lock submit on it. */
  onPolishPendingChange?: (pending: boolean) => void;
  skillMention?: PromptSkillMention;
  /** `useAppliedSkills`'s `chips` — the removable "@技能" pill row. */
  skillChips?: React.ReactNode;
  /** `useAppliedSkills`'s `unlockDialog`. */
  unlockDialog?: React.ReactNode;
  /** A short, condition-specific line under the field — image's `referenceRequiredHint`. */
  hint?: string;
  /**
   * The "写得更像导演" writing-tip copy — video and audio. Folds what used
   * to be `GenerationStudioShell`'s standalone `directHint` box into this
   * card's own header instead of stacking two boxes. Image intentionally
   * passes nothing here (that copy never applied well to a still image) —
   * see `hideDirectHint` at the call site.
   */
  tip?: { title: string; body: string };
  /** Clip studio: the colour-block preview of this suggested cut. */
  after?: React.ReactNode;
}) {
  return (
    <section
      aria-label={tip?.title}
      className="relative flex flex-col gap-3 rounded-[var(--radius-md)] border border-primary/20 bg-gradient-to-br from-primary/8 via-surface-raised to-surface-raised p-4 shadow-raised sm:p-5"
    >
      <span
        aria-hidden="true"
        className="absolute right-4 top-4 flex size-9 items-center justify-center rounded-full bg-primary/15 text-primary"
      >
        <IconSparkle className="size-4" />
      </span>

      {tip ? (
        <div className="pr-10">
          <p className="text-sm font-medium text-text">{tip.title}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">{tip.body}</p>
        </div>
      ) : null}

      <div className={tip ? undefined : 'pr-10'}>
        <PromptField
          prompt={prompt}
          onChange={onChange}
          polishContext={polishContext}
          onPolishAccept={onPolishAccept}
          closePolishSignal={closePolishSignal}
          onPolishBlockedChange={onPolishBlockedChange}
          onPolishPendingChange={onPolishPendingChange}
          skillMention={skillMention}
          maxLength={STUDIO_PROMPT_MAX_LENGTH}
        />
        {after}
        {skillChips}
        {unlockDialog}
        {hint ? <p className="mt-2 text-xs text-muted">{hint}</p> : null}
      </div>
    </section>
  );
}
