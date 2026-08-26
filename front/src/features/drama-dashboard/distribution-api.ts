import { api, newIdempotencyKey } from '@/lib/api/client';

export interface ConfigStatus {
  douyin: boolean;
  kuaishou: boolean;
}

export interface PlatformAccountLink {
  id: string;
  channel: string;
  external_account_id: string;
  external_account_label: string | null;
  status: string;
  connected_at: string;
  token_expires_at: string | null;
}

export interface PublicationFanoutItem {
  channel: string;
  status: string;
  external_post_id: string | null;
  error: string | null;
  reason: string | null;
}

export interface PublicationFanoutResult {
  work_id: string;
  results: PublicationFanoutItem[];
}

export function getConfigStatus() {
  return api.get<ConfigStatus>('/v1/platform-accounts/config-status');
}

export function getAuthorizeUrl(channel: string) {
  return api.get<{ authorize_url: string }>(`/v1/platform-accounts/${channel}/connect`);
}

export function completeConnect(channel: string, code: string, state: string) {
  return api.get<PlatformAccountLink>(
    `/v1/platform-accounts/${channel}/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
  );
}

export function listPlatformAccounts() {
  return api.get<PlatformAccountLink[]>('/v1/platform-accounts');
}

export function disconnectPlatformAccount(linkId: string) {
  return api.delete<PlatformAccountLink>(`/v1/platform-accounts/${linkId}`);
}

export function publishFanout(
  workId: string,
  input: { channels: string[]; title: string; description?: string; hashtags?: string[] },
) {
  return api.post<PublicationFanoutResult>(
    `/v1/works/${workId}/publications:fanout`,
    input,
    { idempotencyKey: newIdempotencyKey() },
  );
}
