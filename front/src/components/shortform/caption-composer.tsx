'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Field, TextArea, TextInput } from '@/components/ui/field';
import { IconClose, IconPlus, IconSparkle } from '@/components/ui/icons';
import type { ShortformProfile } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { AI_DISCLOSURE_TAG, addHashtag, hasDisclosure } from '@/lib/shortform';

/** The three fields a destination app's composer asks for. */
export interface Caption {
  title: string;
  description: string;
  hashtags: string[];
}

export const EMPTY_CAPTION: Caption = { title: '', description: '', hashtags: [] };

/** The API's own ceilings, so a request is never sent that it would reject. */
const TITLE_HARD_LIMIT = 200;
const DESCRIPTION_HARD_LIMIT = 2000;

/**
 * Title, description and hashtags, counted against the selected spec.
 *
 * The inputs are capped at the API's ceiling rather than the profile's: a title
 * two characters over the destination app's limit is a fixable mistake the
 * checklist names, and silently refusing the keystroke would leave the author
 * wondering which of the two rules stopped them.
 */
export function CaptionComposer({
  profile,
  value,
  onChange,
  fieldErrors,
  className,
}: {
  profile: ShortformProfile;
  value: Caption;
  onChange: (next: Caption) => void;
  /** Field paths from a 422, keyed as the API sends them (`title`, `hashtags`). */
  fieldErrors?: Record<string, string>;
  className?: string;
}) {
  const t = useTranslations('shortform');
  const [pending, setPending] = useState('');

  const titleLength = value.title.trim().length;
  const overTitle = titleLength > profile.max_title_length;
  const overHashtags = value.hashtags.length > profile.max_hashtags;
  const needsDisclosure =
    profile.require_ai_disclosure && !hasDisclosure(value.title, value.description, value.hashtags);

  const commitPending = () => {
    if (pending.trim().length === 0) return;
    onChange({ ...value, hashtags: addHashtag(value.hashtags, pending, profile.max_hashtags) });
    setPending('');
  };

  return (
    <section className={cn('flex flex-col gap-4', className)}>
      <div>
        <TextInput
          label={t('titleField')}
          placeholder={t('titlePlaceholder')}
          hint={t('titleHint', { max: profile.max_title_length })}
          error={fieldErrors?.title}
          value={value.title}
          maxLength={TITLE_HARD_LIMIT}
          onChange={(event) => onChange({ ...value, title: event.target.value })}
        />
        <p
          className={cn(
            'tabular mt-1 text-right text-[11px]',
            overTitle ? 'text-danger' : 'text-muted',
          )}
        >
          {titleLength}/{profile.max_title_length}
        </p>
      </div>

      <TextArea
        label={t('descriptionField')}
        placeholder={t('descriptionPlaceholder')}
        error={fieldErrors?.description}
        value={value.description}
        maxLength={DESCRIPTION_HARD_LIMIT}
        onChange={(event) => onChange({ ...value, description: event.target.value })}
      />

      <Field
        label={t('hashtagsField')}
        hint={t('hashtagsHint', { max: profile.max_hashtags })}
        error={fieldErrors?.hashtags}
      >
        {({ controlId, describedBy }) => (
          <div className="flex flex-col gap-2">
            <div className="flex gap-2">
              <input
                id={controlId}
                aria-describedby={describedBy}
                value={pending}
                placeholder={t('hashtagsPlaceholder')}
                onChange={(event) => setPending(event.target.value)}
                onKeyDown={(event) => {
                  // Enter and comma are how people already end a tag; both keep
                  // focus in the field so a whole set can be typed in one go.
                  if (event.key === 'Enter' || event.key === ',' || event.key === '，') {
                    event.preventDefault();
                    commitPending();
                  }
                }}
                onBlur={commitPending}
                className="h-11 w-full min-w-0 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 text-text transition-colors placeholder:text-muted/70"
              />
              <Button
                variant="secondary"
                icon={<IconPlus className="size-4" />}
                disabled={pending.trim().length === 0}
                onClick={commitPending}
                className="shrink-0"
              >
                {t('hashtagAdd')}
              </Button>
            </div>

            {value.hashtags.length > 0 ? (
              <ul className="flex flex-wrap gap-2">
                {value.hashtags.map((tag) => (
                  <li key={tag}>
                    <span className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-soft py-0.5 pl-2 pr-0.5 text-xs">
                      #{tag}
                      <button
                        type="button"
                        aria-label={t('hashtagRemove', { tag })}
                        onClick={() =>
                          onChange({
                            ...value,
                            hashtags: value.hashtags.filter((item) => item !== tag),
                          })
                        }
                        className="grid size-6 place-items-center rounded text-muted transition-colors hover:text-danger focus-visible:outline-2"
                      >
                        <IconClose className="size-3" />
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}

            <p className={cn('tabular text-[11px]', overHashtags ? 'text-danger' : 'text-muted')}>
              {t('hashtagCounter', {
                count: value.hashtags.length,
                max: profile.max_hashtags,
              })}
            </p>

            {needsDisclosure ? (
              <Button
                size="sm"
                variant="secondary"
                icon={<IconSparkle className="size-4" />}
                onClick={() =>
                  onChange({
                    ...value,
                    hashtags: addHashtag(value.hashtags, AI_DISCLOSURE_TAG, profile.max_hashtags),
                  })
                }
                className="self-start"
              >
                {t('disclosureSuggest', { tag: AI_DISCLOSURE_TAG })}
              </Button>
            ) : null}
          </div>
        )}
      </Field>
    </section>
  );
}
