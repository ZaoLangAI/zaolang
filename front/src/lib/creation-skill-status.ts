import type { BadgeTone } from '@/components/ui/primitives';
import type { CreationSkillStatus } from '@/lib/api/types';

/** Badge tone for a creation-skill lifecycle status — shared by the plaza, character library, and scene library. */
export const CREATION_SKILL_STATUS_TONE: Record<CreationSkillStatus, BadgeTone> = {
  draft: 'neutral',
  pending_review: 'amber',
  published: 'success',
  rejected: 'danger',
};

/** `skillLibrary.*` message keys for the same status set. */
export const CREATION_SKILL_STATUS_LABEL_KEY: Record<
  CreationSkillStatus,
  'statusDraft' | 'statusPendingReview' | 'statusPublished' | 'statusRejected'
> = {
  draft: 'statusDraft',
  pending_review: 'statusPendingReview',
  published: 'statusPublished',
  rejected: 'statusRejected',
};
