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

export type WorkSummary = S['WorkSummary'];
export type WorkDetail = S['WorkDetail'];
export type WorkVersionSummary = S['WorkVersionSummary'];
export type ReusableParams = S['ReusableParams'];
export type LicenseInfo = S['LicenseInfo'];
export type LineageResponse = S['LineageResponse'];
export type LineageNode = S['LineageNodeResponse'];
export type LineageAncestor = S['LineageAncestor'];
export type VersionDiff = S['VersionDiffResponse'];

export type Draft = S['DraftResponse'];
export type GenerationJob = S['GenerationJobResponse'];
export type JobEvent = S['JobEventResponse'];
export type Quote = S['QuoteResponse'];
export type RouteSummary = S['RouteSummary'];

export type Collection = S['CollectionResponse'];
export type Notification = S['NotificationResponse'];
export type LedgerEntry = S['LedgerEntryResponse'];
export type CreditPackage = S['CreditPackageResponse'];
export type StylePreset = S['StylePresetResponse'];
export type Tag = S['TagResponse'];
export type GatewayStatus = S['GatewayStatusResponse'];
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
