'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { IconAlert, IconCheck, IconClock } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { ComplianceCheck, ShortformProfile } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { hasDisclosure } from '@/lib/shortform';

/**
 * Rule names are translated from the code, not from the sentence.
 *
 * The API sends one message per rule, and those messages are the server's own
 * copy in one language. Keying the row's *name* off the stable code keeps the
 * checklist readable in all three, while the sentence underneath stays whatever
 * the side that ran the rule said — including a safety verdict the client has no
 * way to phrase for itself.
 */
const RULE_LABEL_KEYS: Record<string, string> = {
  ASPECT_RATIO: 'checkAspectRatio',
  RESOLUTION: 'checkResolution',
  DURATION: 'checkDuration',
  TITLE_LENGTH: 'checkTitleLength',
  HASHTAG_COUNT: 'checkHashtagCount',
  AI_DISCLOSURE: 'checkAiDisclosure',
  CONTENT_SAFETY: 'checkContentSafety',
  SAFE_AREA: 'checkSafeArea',
};

/**
 * A title beyond this share of the limit starts wrapping into the app's own
 * controls. Author-facing guidance, which is why it never blocks.
 */
const SAFE_TITLE_SHARE = 0.6;

export interface PreflightInput {
  profile: ShortformProfile;
  aspectRatio: string;
  durationSeconds: number;
  title: string;
  description: string;
  hashtags: string[];
}

/**
 * The checklist before a clip exists.
 *
 * Same codes and levels the API returns, so the panel does not care which side
 * produced a row, and the author is not made to generate a video before finding
 * out the caption is missing its AI disclosure.
 */
export function usePreflightChecks(input: PreflightInput): ComplianceCheck[] {
  const t = useTranslations('shortform');
  const { profile, aspectRatio, durationSeconds, title, description, hashtags } = input;
  const safeArea = useSafeAreaCheck(title, profile);
  const trimmed = title.trim();

  const checks: ComplianceCheck[] = [];

  checks.push(
    aspectRatio === profile.aspect_ratio
      ? {
          code: 'ASPECT_RATIO',
          level: 'pass',
          message: t('preflightAspect', { ratio: profile.aspect_ratio }),
        }
      : {
          code: 'ASPECT_RATIO',
          level: 'block',
          message: t('preflightAspectBlocked', {
            ratio: profile.aspect_ratio,
            current: aspectRatio,
          }),
        },
  );

  checks.push({
    code: 'RESOLUTION',
    level: 'pass',
    message: t('preflightResolution', { width: profile.width, height: profile.height }),
  });

  const withinRange =
    durationSeconds >= profile.min_duration_seconds &&
    durationSeconds <= profile.max_duration_seconds;
  checks.push({
    code: 'DURATION',
    level: withinRange ? 'pass' : 'block',
    message: withinRange
      ? t('preflightDuration', { seconds: durationSeconds })
      : t('preflightDurationBlocked', {
          min: profile.min_duration_seconds,
          max: profile.max_duration_seconds,
        }),
  });

  if (trimmed.length === 0) {
    checks.push({ code: 'TITLE_LENGTH', level: 'warn', message: t('preflightTitleEmpty') });
  } else if (trimmed.length > profile.max_title_length) {
    checks.push({
      code: 'TITLE_LENGTH',
      level: 'block',
      message: t('preflightTitleBlocked', {
        max: profile.max_title_length,
        count: trimmed.length,
      }),
    });
  } else {
    checks.push({
      code: 'TITLE_LENGTH',
      level: 'pass',
      message: t('preflightTitle', { count: trimmed.length, max: profile.max_title_length }),
    });
  }

  checks.push(
    hashtags.length > profile.max_hashtags
      ? {
          code: 'HASHTAG_COUNT',
          level: 'block',
          message: t('preflightHashtagsBlocked', { max: profile.max_hashtags }),
        }
      : {
          code: 'HASHTAG_COUNT',
          level: 'pass',
          message: t('preflightHashtags', {
            count: hashtags.length,
            max: profile.max_hashtags,
          }),
        },
  );

  if (!profile.require_ai_disclosure) {
    checks.push({
      code: 'AI_DISCLOSURE',
      level: 'pass',
      message: t('preflightDisclosureNotRequired'),
    });
  } else if (hasDisclosure(title, description, hashtags)) {
    checks.push({ code: 'AI_DISCLOSURE', level: 'pass', message: t('preflightDisclosure') });
  } else {
    checks.push({
      code: 'AI_DISCLOSURE',
      level: 'block',
      message: t('preflightDisclosureBlocked'),
    });
  }

  checks.push(safeArea);

  // The real verdict comes from the moderation agent once there is a clip to
  // check, so this row exists to say the step is still ahead rather than passed.
  checks.push({ code: 'CONTENT_SAFETY', level: 'warn', message: t('preflightSafety') });

  return checks;
}

/** Local advisory, appended to the API's rows: it has no server-side twin. */
export function useSafeAreaCheck(title: string, profile: ShortformProfile): ComplianceCheck {
  const t = useTranslations('shortform');
  const budget = Math.round(profile.max_title_length * SAFE_TITLE_SHARE);

  if (title.trim().length > budget) {
    return { code: 'SAFE_AREA', level: 'warn', message: t('preflightSafeAreaTight', { budget }) };
  }
  return {
    code: 'SAFE_AREA',
    level: 'pass',
    message: t('preflightSafeArea', {
      bottom: profile.safe_area_bottom_pct,
      right: profile.safe_area_right_pct,
    }),
  };
}

export function blockingChecks(items: ComplianceCheck[]): ComplianceCheck[] {
  return items.filter((item) => item.level === 'block');
}

const levelStyles: Record<ComplianceCheck['level'], string> = {
  pass: 'text-success',
  warn: 'text-amber',
  block: 'text-danger',
};

/**
 * The pre-publish checklist.
 *
 * Every rule is listed with its own verdict rather than collapsed into one
 * pass/fail, so a creator fixes everything in a single pass instead of
 * rediscovering the next problem after each attempt.
 */
export function CompliancePanel({
  items,
  title,
  hint,
  loading = false,
  error,
  onRecheck,
  recheckLabel,
  className,
}: {
  items: ComplianceCheck[];
  title: string;
  hint?: string;
  loading?: boolean;
  error?: string | null;
  onRecheck?: () => void;
  recheckLabel?: string;
  className?: string;
}) {
  const t = useTranslations('shortform');
  const blocking = blockingChecks(items);

  return (
    <section
      className={cn(
        'flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4',
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
        </div>
        {onRecheck && recheckLabel ? (
          <Button size="sm" variant="secondary" loading={loading} onClick={onRecheck}>
            {recheckLabel}
          </Button>
        ) : null}
      </div>

      {error ? <ErrorNotice title={error} /> : null}

      {loading && items.length === 0 ? (
        <p className="flex items-center gap-2 text-xs text-muted">
          <Spinner className="size-3.5" />
          {t('compliancePending')}
        </p>
      ) : null}

      <ul className="flex flex-col divide-y divide-border">
        {items.map((item) => (
          <li key={item.code} className="flex items-start gap-2.5 py-2 first:pt-0 last:pb-0">
            <span aria-hidden="true" className={cn('mt-0.5 shrink-0', levelStyles[item.level])}>
              {item.level === 'pass' ? (
                <IconCheck className="size-4" />
              ) : item.level === 'warn' ? (
                <IconClock className="size-4" />
              ) : (
                <IconAlert className="size-4" />
              )}
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium">
                {t(RULE_LABEL_KEYS[item.code] ?? 'checkOther')}
                <span className={cn('ml-2 font-normal', levelStyles[item.level])}>
                  {t(
                    item.level === 'pass'
                      ? 'levelPass'
                      : item.level === 'warn'
                        ? 'levelWarn'
                        : 'levelBlock',
                  )}
                </span>
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted">{item.message}</p>
            </div>
          </li>
        ))}
      </ul>

      <p
        role="status"
        className={cn('text-xs', blocking.length > 0 ? 'text-danger' : 'text-success')}
      >
        {blocking.length > 0
          ? t('complianceBlocked', { count: blocking.length })
          : t('compliancePassed')}
      </p>
    </section>
  );
}
