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
export type JobStats = S['JobStatsView'];
export type ProviderAttempt = S['ProviderAttemptView'];
export type ModerationItem = S['ModerationQueueView'];
export type ModerationHistoryEntry = S['ModerationHistoryEntry'];
export type ModerationWorkDetail = S['ModerationWorkDetailView'];
export type ModerationSubjectDetail = S['ModerationSubjectDetailView'];
export type ReportCase = S['ReportCaseView'];
export type LearnPostAdminView = S['LearnPostAdminView'];
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
export type LogEntry = S['LogEntryView'];
export type Announcement = S['AnnouncementView'];
export type LlmProviderEndpoint = S['LlmProviderEndpointView'];
export type LlmProviderCategory = S['LlmProviderCategoryView'];
export type LlmProviderPool = S['LlmProviderPoolView'];
export type LlmProviderUpsertRequest = S['LlmProviderEndpointUpsertRequest'];
export type MediaCapability = S['MediaCapabilityView'];
export type LlmProviderKind = LlmProviderEndpoint['kind'];
export type AgentNode = S['AgentNodeView'];
export type AgentSkill = S['AgentSkillView'];
export type CreationSkillAdminView = S['CreationSkillAdminView'];
export type RedemptionCode = S['RedemptionCodeView'];
export type RedemptionRecord = S['RedemptionRecordView'];
export type RedemptionCodeKind = S['RedemptionCodeKind'];
export type Page<T> = { items: T[]; next_cursor?: string | null; has_more?: boolean };

/**
 * `GET /v1/admin/workflow` returns a plain `dict` on the backend (see
 * `app/workflows/generation.describe_workflow`), so it has no generated
 * schema type — this mirrors that shape by hand.
 */
export interface WorkflowStep {
  key: string;
  label: string;
  node_type: string;
  event_type: string;
  is_agent: boolean;
  agent_role?: string | null;
}

export interface WorkflowShape {
  operation: string;
  name: string;
  version: number | null;
  description: string;
  steps: WorkflowStep[];
}

// The configurable node-graph editor (`/admin/routing` → 工作流编排 tab).
export type NodeTypeView = S['NodeTypeView'];
export type WorkflowTemplateView = S['WorkflowTemplateView'];
export type WorkflowTemplatePublishRequest = S['WorkflowTemplatePublishRequest'];
export type WorkflowTemplateValidateResponse = S['WorkflowTemplateValidateResponse'];
export type WorkflowDryRunRequest = S['WorkflowDryRunRequest'];
export type WorkflowDryRunResult = S['WorkflowDryRunResult'];
export type WorkflowDryRunStepView = S['WorkflowDryRunStepView'];

/** One node in `WorkflowTemplateView.graph` — the backend keeps this as an
 * untyped `dict` (`app.workflows.graph.WorkflowGraph.to_dict`), so the shape
 * is mirrored here by hand rather than generated. */
export interface WorkflowGraphNode {
  id: string;
  type: string;
  config: Record<string, unknown>;
  position: { x: number; y: number };
}

export type WorkflowEdgeKind = 'sequential' | 'parallel' | 'retry';

export interface WorkflowGraphEdge {
  id: string;
  from: string;
  from_port: string;
  to: string;
  kind: WorkflowEdgeKind;
}

export interface WorkflowGraphJson {
  nodes: WorkflowGraphNode[];
  edges: WorkflowGraphEdge[];
}
