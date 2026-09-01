'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { useRouter } from '@/i18n/navigation';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Draft, GenerationJob, Operation, QualityTier, Quote } from '@/lib/api/types';

/** The inputs the price depends on.
 *
 * `assetKind`/`characterViews` are optional because most callers price a
 * single, ordinary output — but a multi-view character completion (see
 * `character-library.tsx` and `ImageGenerationStudio`'s own completion
 * submit) costs one image per view (`character_output_count` on the
 * backend), and omitting them here would quote 1× while `submit()` reserves
 * N×, exactly the estimate/charge mismatch this pair of fields closes.
 */
export interface GenerationQuoteInput {
  operation: Operation;
  qualityTier: QualityTier;
  durationSeconds: number;
  assetKind?: 'general' | 'character' | 'scene' | 'cover';
  characterViews?: ('front' | 'side' | 'back')[];
}

export interface GenerationSubmitInput extends GenerationQuoteInput {
  prompt: string;
  aspectRatio: string;
  seed?: number;
  referenceAssetIds: string[];
  videoOptions?: {
    resolution?: '480p' | '720p' | '1080p' | '2K';
    reference_mode: 'input_references' | 'frame_images';
    first_frame_asset_id?: string | null;
    last_frame_asset_id?: string | null;
  };
  /** Cast picked from the character library; merged server-side into the job's
   * reference images and voice hints (see `characters.service.apply_character_refs`). */
  characterIds?: string[];
  /** Settings picked from the scene library; merged server-side into the job's
   * reference images (see `scenes.service.apply_scene_refs`), sharing the same
   * reference-slot budget as `characterIds` above. */
  sceneIds?: string[];
  /**
   * What a `text_to_image`/`image_to_image` output is *for* — orthogonal to
   * `operation`. Selects the `(operation, asset_kind)` workflow template and,
   * for `character`/`scene`, what `execute_asset_output_link` auto-attaches
   * the succeeded output(s) to. Absent (or `'general'`) is today's plain,
   * freeform image — unchanged.
   */
  assetKind?: 'general' | 'character' | 'scene' | 'cover';
  /**
   * The video-side equivalent of `assetKind` — what a `text_to_video`/
   * `image_to_video`/`video_to_video` output is *for*, orthogonal to
   * `operation` the same way. Selects the `(operation, video_asset_kind)`
   * workflow template and, for `character_action`/`scene_video`, what
   * `execute_asset_output_link` auto-attaches the succeeded output to (a
   * character's `action_clips` or a scene's `clips`, not a still reference).
   * Absent (or `'general'`) is today's plain video generation, unchanged.
   * A submit sets at most one of `assetKind`/`videoAssetKind`.
   */
  videoAssetKind?:
    'general' | 'scene_video' | 'character_action' | 'transition_video' | 'cover_video';
  /**
   * Only meaningful with `assetKind: 'character'`: which of front/side/back
   * this job produces, one at a time. Omitted means `['front']` — a plain
   * single-view request. The character library's "补全侧面/背面" button is
   * the one caller that names `['side', 'back']` explicitly.
   */
  characterViews?: ('front' | 'side' | 'back')[];
  /** The character skill this output auto-attaches to. Unset with a
   * character `assetKind`/`videoAssetKind: 'character_action'` creates a
   * brand-new character skill instead. */
  targetCharacterId?: string | null;
  /** The scene this output auto-attaches to. Unset with `assetKind: 'scene'`/
   * `videoAssetKind: 'scene_video'` auto-creates a brand-new scene skill
   * instead (parity with the character path above — see
   * `zaolang-generation-jobs` invariant 15). */
  targetSceneId?: string | null;
  /**
   * Overrides the planner's own guessed name when auto-creating a new
   * character/scene skill (no `targetCharacterId`/`targetSceneId`). Only
   * meaningful for a caller that already knows the exact name — e.g. the
   * script studio's "生成角色图/场景图" jump-out, which carries the script's
   * own character name/scene heading. Ignored once a target id is set.
   */
  subjectNameHint?: string;
  /**
   * Opts out of the auto-attach above while still letting `assetKind`/
   * `videoAssetKind` shape the generation itself. Defaults to `true`.
   */
  autoAttachAsset?: boolean;
  /** Free-form provider hints, e.g. `{ sound: true }`. */
  extra?: Record<string, unknown>;
  /**
   * The `CreationSkill`s applied to this request, in pick order. The studio
   * already merged their params into `prompt`/`extra` locally; this lets the
   * `skill_context` workflow node re-apply them authoritatively server-side.
   */
  skillIds?: string[];
  /** Platform style-catalogue entry; `skill_context` re-fetches its params. */
  styleGalleryId?: string;
  /** A licensed remix source. Carried by both the draft and the job. */
  sourceWorkId?: string;
  /** Ceiling sent to the API; the job is refused rather than trimmed. */
  maxCredits?: number;
  draftTitle?: string | null;
  /**
   * Reuses an existing draft instead of creating a new one — the image and
   * video studios' inline "continue refining" flow both pass the draft id
   * from their previous submission so every iteration of the same creative
   * idea stays on one draft (and therefore shows up together in
   * `GenerationVersionHistory`), rather than each generate click spawning
   * its own unpublishable draft.
   */
  draftId?: string;
  /**
   * Names a `shortform.profiles` entry. The API refuses the job when it
   * contradicts the aspect ratio or the duration, so it travels with them.
   */
  shortformProfile?: string;
  /**
   * Extra keys merged into the draft's params.
   *
   * The draft is the only thing that outlives the job, so anything the steps
   * after generation need — a caption written while framing the shot, say — has
   * to be stored on it rather than in component state.
   */
  draftParams?: Record<string, unknown>;
  /**
   * The short-drama workspace's own deep link (`?linkEpisodeId=`, read back
   * by `/create/new`'s `page.tsx`) — written onto the new draft as
   * `params.link_episode_id` so `POST /v1/drafts` can attach it as a
   * `candidate` content-link in the same transaction. A still-running or
   * failed attempt is still material worth keeping visible in the workspace.
   */
  linkEpisodeId?: string;
  /**
   * Which script breakpoint this video belongs to (`{heading}#{ordinal}`).
   * Stored on the draft as `params.link_breakpoint_key` so the script
   * studio can flip that chip from "建议切分" to "查看视频".
   */
  linkBreakpointKey?: string;
  /**
   * Opts this job out of the LLM-driven routing pick (`intent_router
   * .select_provider`) entirely — the exact `model_or_workflow` string from
   * `GET /v1/generation-jobs/models`. `route_score` still hard-filters the
   * catalogue exactly as usual, but the winner is whichever surviving
   * candidate carries this model, chosen deterministically rather than by
   * the routing agent. No matching candidate is a hard failure — there is
   * no silent fallback to the normal auto-routed pick. Only meaningful for
   * image/video creation (see `back/app/api/schemas/jobs.py`
   * `validate_generation_params`); omitted (the default) is today's
   * unchanged auto-routed behaviour.
   */
  forcedModel?: string;
}


export interface GenerationSubmit {
  quote: Quote | null;
  /** The quote call failed; the estimate on screen is stale or absent. */
  quoteFailed: boolean;
  submitting: boolean;
  error: string | null;
  /** Field paths from a 422, so a shell can show them next to the control. */
  fieldErrors: Record<string, string>;
  /** Goes through the login wall, then creates the draft and the job. */
  submit: (input: GenerationSubmitInput) => void;
}

const QUOTE_DEBOUNCE_MS = 250;

/**
 * Quoting and submitting a generation, shared by every studio shell.
 *
 * `ImageGenerationStudio`, `VideoGenerationStudio` and `AudioGenerationStudio`
 * are independent top-level components — their params panels differ enough
 * (asset kind vs. duration/frames vs. voice) that forcing them into one
 * component meant branching on operation type everywhere. But `/create/new`
 * and `/remix/[workId]` still submit the same job with the same pricing
 * rules, so all three shells call this one hook rather than each growing
 * their own copy: the debounce, the login wall, the draft, the idempotency
 * key and the destination are the parts that would drift silently and
 * expensively if duplicated.
 */
export function useGenerationSubmit(
  quoteInput: GenerationQuoteInput,
  {
    label,
    onSubmitted,
  }: {
    label: string;
    /**
     * When provided, a successful submission calls this instead of
     * navigating to `/jobs/[jobId]` — the image and video studios' inline
     * flow both use this to stay on the studio page and stream progress
     * into their own preview slot. The audio studio doesn't pass it, so its
     * navigate-away behaviour is unchanged.
     */
    onSubmitted?: (job: GenerationJob) => void;
  },
): GenerationSubmit {
  const tStates = useTranslations('states');
  const router = useRouter();
  const { requireAuth, status: sessionStatus } = useSession();

  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteFailed, setQuoteFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const { operation, qualityTier, durationSeconds, assetKind, characterViews } = quoteInput;
  // Stable dependency key for the effect below — `characterViews` is a new
  // array identity on every render even when its contents haven't changed.
  const characterViewsKey = characterViews?.join(',') ?? '';

  // Re-quote whenever a priced input changes. Debounced because the tier and
  // duration controls are adjacent and users sweep across them.
  const latestQuote = useRef(0);
  useEffect(() => {
    if (sessionStatus !== 'authenticated') return;
    const ticket = ++latestQuote.current;
    const timer = setTimeout(() => {
      void api
        .post<Quote>('/v1/generation-jobs/quote', {
          operation,
          quality_tier: qualityTier,
          duration_seconds: durationSeconds,
          asset_kind: assetKind ?? 'general',
          character_views: characterViews ?? null,
        })
        .then((body) => {
          if (ticket !== latestQuote.current) return;
          setQuote(body);
          setQuoteFailed(false);
        })
        .catch(() => {
          if (ticket !== latestQuote.current) return;
          setQuoteFailed(true);
        });
    }, QUOTE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operation, qualityTier, durationSeconds, assetKind, characterViewsKey, sessionStatus]);

  /**
   * Kept across a failed attempt so a retry reuses the same draft instead of
   * leaving a trail of empty ones in the user's library. Cleared as soon as a
   * job is attached to it.
   */
  const pendingDraft = useRef<string | null>(null);
  /**
   * One key per pending submission, not one per click: a network failure (or
   * any client-side timeout) leaves the server's outcome unknown, and
   * re-minting a key on retry would let that lost request *and* the retry
   * both reserve credits. The key is only cleared once a job id actually
   * comes back — see `zaolang-credits-billing` invariant 5.
   */
  const pendingIdempotencyKey = useRef<string | null>(null);

  const submit = (input: GenerationSubmitInput) =>
    requireAuth({
      label,
      run: async () => {
        setSubmitting(true);
        setError(null);
        setFieldErrors({});
        try {
          // An explicit `draftId` (the image studio reusing its own earlier
          // draft across iterations) always wins over a draft left over from
          // a previous failed attempt.
          if (input.draftId) pendingDraft.current = input.draftId;

          // The draft is what `/publish/[draftId]` and the job page's publish
          // button hang off; a job submitted without one produces a result the
          // user cannot publish.
          if (pendingDraft.current === null) {
            const draft = await api.post<Draft>('/v1/drafts', {
              source_work_id: input.sourceWorkId ?? null,
              title: input.draftTitle ?? null,
              params: {
                prompt: input.prompt,
                aspect_ratio: input.aspectRatio,
                duration_seconds: input.durationSeconds,
                seed: input.seed,
                video_options: input.videoOptions,
                operation: input.operation,
                quality_tier: input.qualityTier,
                ...(input.shortformProfile
                  ? { shortform_profile: input.shortformProfile }
                  : undefined),
                ...input.draftParams,
                ...(input.linkEpisodeId ? { link_episode_id: input.linkEpisodeId } : undefined),
                ...(input.linkBreakpointKey
                  ? { link_breakpoint_key: input.linkBreakpointKey }
                  : undefined),
              },
            });
            pendingDraft.current = draft.id;
          }

          pendingIdempotencyKey.current ??= newIdempotencyKey();
          const job = await api.post<GenerationJob>(
            '/v1/generation-jobs',
            {
              operation: input.operation,
              quality_tier: input.qualityTier,
              draft_id: pendingDraft.current,
              source_work_id: input.sourceWorkId,
              params: {
                prompt: input.prompt,
                seed: input.seed,
                aspect_ratio: input.aspectRatio,
                duration_seconds: input.durationSeconds,
                reference_asset_ids: input.referenceAssetIds,
                video_options: input.videoOptions,
                character_ids: input.characterIds ?? [],
                scene_ids: input.sceneIds ?? [],
                shortform_profile: input.shortformProfile,
                skill_ids: input.skillIds ?? [],
                style_gallery_id: input.styleGalleryId ?? null,
                asset_kind: input.assetKind ?? 'general',
                video_asset_kind: input.videoAssetKind ?? 'general',
                character_views: input.characterViews ?? null,
                target_character_id: input.targetCharacterId ?? null,
                target_scene_id: input.targetSceneId ?? null,
                subject_name_hint: input.subjectNameHint,
                auto_attach_asset: input.autoAttachAsset ?? true,
                forced_model: input.forcedModel ?? null,
                extra: input.extra ?? {},
              },
              max_credits: input.maxCredits,
            },
            { idempotencyKey: pendingIdempotencyKey.current },
          );
          pendingDraft.current = null;
          pendingIdempotencyKey.current = null;
          if (onSubmitted) {
            onSubmitted(job);
            setSubmitting(false);
          } else {
            router.push(`/jobs/${job.id}`);
          }
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
          if (caught instanceof ApiError) {
            setFieldErrors(caught.fieldErrors);
            // The stored key now belongs to a request body that no longer
            // matches (the user changed an input between attempts) — keeping
            // it would only 409 forever, so the next attempt mints a new one.
            if (caught.code === 'IDEMPOTENCY_CONFLICT') pendingIdempotencyKey.current = null;
          }
          setSubmitting(false);
        }
      },
    });

  return { quote, quoteFailed, submitting, error, fieldErrors, submit };
}
