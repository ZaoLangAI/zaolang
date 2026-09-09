import type { components } from '@/lib/api/schema';

/**
 * Named aliases for the generated schema.
 *
 * `components['schemas'][...]` is unreadable at call sites, and re-exporting
 * here means a renamed backend model surfaces as a single compile error rather
 * than as a scattered find-and-replace.
 */
type S = components['schemas'];

export type Me = S['MeResponse'];
export type Profile = S['ProfileResponse'];
export type PublicProfile = S['PublicProfileResponse'];
export type AuthorSummary = S['AuthorSummary'];

export type LearnPostSummary = S['LearnPostSummary'];
export type LearnPostDetail = S['LearnPostDetail'];
export type LearnPostLevel = S['LearnPostLevel'];
export type LearnPostStatus = S['LearnPostStatus'];
/** 别名到最完整的形态，与后端 `LearnPost` 模型对齐；调用点按需选用 Summary/Detail 即可。 */
export type LearnPost = LearnPostDetail;

export type WorkSummary = S['WorkSummary'];
export type TrashWorkSummary = S['TrashWorkSummary'];
export type WorkDetail = S['WorkDetail'];
export type WorkVersionSummary = S['WorkVersionSummary'];
export type ReusableParams = S['ReusableParams'];
export type LicenseInfo = S['LicenseInfo'];
export type LineageResponse = S['LineageResponse'];
export type LineageNode = S['LineageNodeResponse'];
export type LineageAncestor = S['LineageAncestor'];
export type VersionDiff = S['VersionDiffResponse'];
export type VersionDiffEntry = S['VersionDiffEntry'];
export type WorkAppeal = S['WorkAppealView'];

export type Draft = S['DraftResponse'];
export type Asset = S['AssetResponse'];
export type GenerationJob = S['GenerationJobResponse'];
export type JobEvent = S['JobEventResponse'];
export type Quote = S['QuoteResponse'];
export type GenerationModelOption = S['GenerationModelOption'];
export type GenerationModelListResponse = S['GenerationModelListResponse'];
export type RouteSummary = S['RouteSummary'];
export type VideoAnalysisResult = S['VideoAnalysisResult'];
export type VideoAnalysisShot = S['VideoAnalysisShot'];

export type ShortformProfile = S['ShortformProfileResponse'];
export type ShortformProfiles = S['ShortformProfilesResponse'];
export interface PromptEnhanceScriptBlock {
  type: 'scene' | 'action' | 'camera' | 'dialogue';
  character: string | null;
  text: string;
}

export interface PromptEnhanceScriptSegment {
  heading: string;
  blocks: PromptEnhanceScriptBlock[];
}

export type PromptEnhancePayload = S['PromptEnhanceRequest'] & {
  script_segment?: PromptEnhanceScriptSegment;
  /** Answers to the previous round's `questions`, keyed by question id. */
  question_answers?: Record<string, string | string[]>;
};
// `/generation/prompts/enhance` is a `StreamingResponse` (see
// `api/v1/prompts.py`), so its final frame — `PromptEnhanceResponse` on the
// backend — never gets a `response_model` and so never appears in
// `openapi.json`. Mirrored here by hand instead, same as `PromptDimensionView`.
export interface PromptEnhanceDimension {
  key:
    | 'subject'
    | 'scene'
    | 'action'
    | 'camera'
    | 'lighting'
    | 'mood'
    | 'pacing'
    | 'composition'
    | 'style'
    | 'detail';
  status: 'missing' | 'weak' | 'ok';
  hint: string;
}
/** Same shape as a job's awaiting-input question, so both render through
 * `QuestionField`. Scene plates are the only kind that asks today. */
export interface PromptEnhanceQuestion {
  id: string;
  kind: 'single_choice' | 'multi_choice' | 'free_text';
  prompt: string;
  options?: Array<{ value: string; label: string }>;
  required?: boolean;
}
export interface PromptEnhanceResult {
  prompt: string;
  detail_level: 'sparse' | 'adequate' | 'detailed';
  feedback: string;
  dimensions: PromptEnhanceDimension[];
  additions: string[];
  questions?: PromptEnhanceQuestion[];
  script_segment?: PromptEnhanceScriptSegment;
}
export type JobInputQuestion = S['JobInputQuestionView'];
export type JobInputRequest = S['JobInputRequestResponse'];
export type JobAnswerItem = S['JobAnswerItem'];
export type DistributionChannel = S['DistributionChannel'];
export type PublicationStatus = S['PublicationStatus'];

export type Character = S['CharacterResponse'];
export type Scene = S['SceneResponse'];

export type DramaSeries = S['DramaSeriesResponse'];
export type DramaEpisode = S['DramaEpisodeResponse'];
export type EpisodeContentLink = S['EpisodeContentLinkResponse'];
export type EpisodeCut = S['EpisodeCutResponse'];
export type CutRevision = S['CutRevisionResponse'];
export type EditorLease = S['LeaseResponse'];
export type EditPlan = S['EditPlanResponse'];
export type DeliveryVariant = S['DeliveryVariantResponse'];
export type EditorExport = S['EditorExportResponse'];
export type EditorOperation = S['EditorOperationResponse'];

export type Collection = S['CollectionResponse'];
export type Notification = S['NotificationResponse'];
export type LedgerEntry = S['LedgerEntryResponse'];
export type CreditPackage = S['CreditPackageResponse'];
export type CheckoutIntent = S['CheckoutIntentResponse'];
export type CheckoutConfirmResult = S['CheckoutConfirmResponse'];
export type StylePreset = S['StylePresetResponse'];
export type StyleGalleryEntry = S['StyleGalleryEntryResponse'];
export type CreationSkillSummary = S['CreationSkillSummary'];
export type CreationSkillDetail = S['CreationSkillDetail'];
export type CreationSkillCategory = S['CreationSkillCategory'];
export type CreationSkillStatus = S['CreationSkillStatus'];
export type CreationSkillVisibility = S['CreationSkillVisibility'];
export type Tag = S['TagResponse'];
export type RedeemCodeRequest = S['RedeemCodeRequest'];
export type RedeemCodeResponse = S['RedeemCodeResponse'];
export type CountResponseLike = S['CountResponse'];

export type Visibility = S['Visibility'];
export type LifecycleStatus = S['LifecycleStatus'];
export type MediaType = S['MediaType'];
export type Operation = S['Operation'];
export type QualityTier = S['QualityTier'];
export type JobStatus = S['JobStatus'];
export type Region = S['Region'];
export type Locale = S['Locale'];
export type ThemePreference = S['ThemePreference'];

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
  has_more?: boolean;
  total?: number | null;
}
