'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Button } from '@/components/ui/button';
import { IconSparkle } from '@/components/ui/icons';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';

type DetailLevel = 'sparse' | 'adequate' | 'detailed';

interface PromptEnhanceResult {
  prompt: string;
  detail_level: DetailLevel;
  feedback: string;
  degraded: boolean;
}

/**
 * The "AI 润色" control shared by `GenerationStudio` and `ShortformStudio`.
 *
 * Both surfaces show the same shape: a button that asks the copy agent to
 * assess how detailed the scene description is, then a suggestion panel the
 * author explicitly accepts or ignores. Neither studio overwrites the field
 * on its own — that was `ShortformStudio`'s old behaviour (replace + undo),
 * which this replaces so both studios read the same way.
 */
export function PromptPolish({
  endpoint,
  prompt,
  onAccept,
  className,
}: {
  /** Different per studio: shortform's is feature-flag gated, the generation studio's is not. */
  endpoint: string;
  prompt: string;
  onAccept: (prompt: string) => void;
  className?: string;
}) {
  const t = useTranslations('promptPolish');
  const tStates = useTranslations('states');
  const { requireAuth } = useSession();

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<PromptEnhanceResult | null>(null);

  const handleRequest = () =>
    requireAuth({
      label: t('button'),
      run: async () => {
        setPending(true);
        setError(null);
        try {
          const result = await api.post<PromptEnhanceResult>(endpoint, { prompt: prompt.trim() });
          setSuggestion(result);
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
        } finally {
          setPending(false);
        }
      },
    });

  const detailLabel: Record<DetailLevel, string> = {
    sparse: t('detailSparse'),
    adequate: t('detailAdequate'),
    detailed: t('detailDetailed'),
  };

  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          icon={<IconSparkle className="size-4" />}
          disabled={prompt.trim().length === 0 || pending}
          loading={pending}
          onClick={handleRequest}
        >
          {pending ? t('buttonPending') : t('button')}
        </Button>
      </div>

      {error ? (
        <p role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      ) : null}

      {suggestion ? (
        <div className="mt-2.5 flex flex-col gap-2.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-primary/12 px-2 py-0.5 text-[11px] font-medium text-primary">
              {detailLabel[suggestion.detail_level]}
            </span>
            <p className="min-w-0 flex-1 text-xs text-muted">{suggestion.feedback}</p>
          </div>
          <p className="text-sm leading-relaxed text-text">{suggestion.prompt}</p>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => {
                onAccept(suggestion.prompt);
                setSuggestion(null);
              }}
            >
              {t('accept')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSuggestion(null)}>
              {t('ignore')}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
