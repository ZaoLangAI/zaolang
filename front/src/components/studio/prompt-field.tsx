'use client';

import { useTranslations } from 'next-intl';

import { PromptPolish, type PromptPolishContext } from '@/components/studio/prompt-polish';
import { TextArea } from '@/components/ui/field';

export const PROMPT_MAX_LENGTH = 600;

/**
 * The prompt textarea + character counter + optional "AI 润色" button,
 * identical across image, video and audio. Audio omits `polishContext` —
 * there is nothing camera/lighting-shaped for the copy agent to critique.
 */
export function PromptField({
  prompt,
  onChange,
  polishContext,
  onPolishAccept,
  closePolishSignal,
}: {
  prompt: string;
  onChange: (value: string) => void;
  polishContext?: PromptPolishContext;
  onPolishAccept?: (prompt: string) => void;
  /** Forwarded to `PromptPolish` — see its own doc comment. */
  closePolishSignal?: number;
}) {
  const t = useTranslations('remixPage');

  return (
    <div>
      <TextArea
        label={t('promptLabel')}
        placeholder={t('promptPlaceholder')}
        value={prompt}
        maxLength={PROMPT_MAX_LENGTH}
        onChange={(event) => onChange(event.target.value)}
      />
      <p className="tabular mt-1 text-right text-[11px] text-muted">
        {prompt.length}/{PROMPT_MAX_LENGTH}
      </p>
      {polishContext && onPolishAccept ? (
        <PromptPolish
          className="mt-2"
          endpoint="/v1/generation/prompts/enhance"
          prompt={prompt}
          context={polishContext}
          onAccept={onPolishAccept}
          closeSignal={closePolishSignal}
        />
      ) : null}
    </div>
  );
}
