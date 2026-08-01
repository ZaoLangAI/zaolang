import type { components } from '@/lib/api/schema';

/**
 * Console-facing aliases for the generated schema.
 *
 * Keeping them in one file means a backend contract change surfaces here as a
 * single compile error rather than in a dozen pages.
 */
type S = components['schemas'];

export type SystemHealth = S['SystemHealthResponse'];
export type ServiceHealth = S['ServiceHealth'];
export type QueueDepth = S['QueueDepth'];
export type ProviderStat = S['ProviderStatView'];
export type RoutingReplay = S['RoutingReplayResponse'];
export type AgentRun = S['AgentRunView'];
export type AgentUsage = S['AgentUsageSummary'];
export type AdminJob = S['AdminJobSummary'];
export type AdminJobDetail = S['AdminJobDetail'];
export type ProviderAttempt = S['ProviderAttemptView'];
export type ModerationItem = S['ModerationQueueView'];
export type ReportCase = S['ReportCaseView'];
export type AdminUser = S['AdminUserView'];
export type DataRequestView = S['DataRequestView'];
export type AdminLedgerEntry = S['LedgerEntryView'];
export type Reconciliation = S['ReconciliationView'];
export type DanglingReserve = S['DanglingReserveView'];
export type ConfigValue = S['ConfigValueResponse'];
export type ConfigVersion = S['ConfigVersionView'];
export type ConfigDiff = S['ConfigDiffResponse'];
export type ConfigDiffEntry = S['ConfigDiffEntry'];
export type FeatureFlag = S['FeatureFlagView'];
export type StorageUsage = S['StorageUsageResponse'];
export type BackupRecord = S['BackupRecordView'];
export type AuditLog = S['AuditLogView'];
export type Announcement = S['AnnouncementView'];
export type Page<T> = { items: T[]; next_cursor?: string | null; has_more?: boolean };
