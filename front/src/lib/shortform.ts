import type { PlatformChrome } from '@/lib/devices';
import type { ShortformProfile } from '@/lib/api/types';

/**
 * Client-side half of the short-video rules.
 *
 * Every limit here is read off the profile the API served, and the API applies
 * the same numbers again on `POST /v1/shortform/compliance-check`. Duplicating
 * the comparison buys instant feedback while typing a caption; it never decides
 * anything, so a profile edited in the config centre changes both sides at once.
 */

/** The hashtag offered when a profile requires an AI disclosure. */
export const AI_DISCLOSURE_TAG = 'AIGC';

/** Mirrors `app/domain/shortform/service.py`, so both sides accept the same set. */
const DISCLOSURE_HASHTAGS = new Set(['ai', 'aigc', 'aigenerated', 'ai生成']);
const DISCLOSURE_MARKERS = ['aigc', 'ai生成', 'ai-generated', 'ai generated', '#ai', '人工智能'];

/** Anything but a word character or CJK ends a hashtag. */
const HASHTAG_SEPARATORS = /[\s,，、;；#]+/;

const DURATION_STEP_SECONDS = 5;

export function isPortrait(profile: ShortformProfile): boolean {
  return profile.height >= profile.width;
}

/** The share of the screen a destination app covers with its own controls. */
export function chromeOf(profile: ShortformProfile): PlatformChrome {
  return {
    top: profile.safe_area_top_pct / 100,
    right: profile.safe_area_right_pct / 100,
    bottom: profile.safe_area_bottom_pct / 100,
  };
}

/**
 * Duration choices for a profile: both ends plus two rounded steps between.
 *
 * Generated rather than listed so a profile whose range an operator widens does
 * not need a matching code change, and so the studio can never offer a length
 * the API would refuse.
 */
export function durationOptions(profile: ShortformProfile): number[] {
  const { min_duration_seconds: min, max_duration_seconds: max } = profile;
  const values = new Set([min, max]);
  const span = max - min;
  for (const share of [1 / 3, 2 / 3]) {
    const rounded =
      Math.round((min + span * share) / DURATION_STEP_SECONDS) * DURATION_STEP_SECONDS;
    if (rounded > min && rounded < max) values.add(rounded);
  }
  return [...values].sort((left, right) => left - right);
}

/** Strips the leading `#` and the whitespace people paste along with a tag. */
export function normaliseHashtag(raw: string): string {
  return raw.trim().replace(/^#+/, '').trim();
}

/** Splits one pasted line into tags, tolerating `#a #b`, `a, b` and `a、b`. */
export function parseHashtags(raw: string): string[] {
  return raw
    .split(HASHTAG_SEPARATORS)
    .map(normaliseHashtag)
    .filter((tag) => tag.length > 0);
}

export function addHashtag(current: string[], raw: string, limit: number): string[] {
  const incoming = parseHashtags(raw).filter(
    (tag) => !current.some((existing) => existing.toLowerCase() === tag.toLowerCase()),
  );
  // Trimmed to the limit here as well as flagged by the checklist: the input
  // should not be able to grow a list the export will then refuse.
  return [...current, ...incoming].slice(0, limit);
}

export function hasDisclosure(title: string, description: string, hashtags: string[]): boolean {
  if (hashtags.some((tag) => DISCLOSURE_HASHTAGS.has(normaliseHashtag(tag).toLowerCase()))) {
    return true;
  }
  const text = `${title} ${description}`.toLowerCase();
  return DISCLOSURE_MARKERS.some((marker) => text.includes(marker));
}

/** The caption as a destination app's composer wants it pasted. */
export function captionText(title: string, description: string, hashtags: string[]): string {
  const tags = hashtags.map((tag) => `#${tag}`).join(' ');
  return [title.trim(), description.trim(), tags].filter((part) => part.length > 0).join('\n\n');
}
