import { api } from '@/lib/api/client';
import type { Asset } from '@/lib/api/types';

/**
 * Mints a fresh attachment-disposition signed URL and navigates to it.
 *
 * Cross-origin `<a download>` is ignored by the browser, and fetching the
 * video as a blob would load the whole file into memory — the signed URL
 * already carries `Content-Disposition: attachment`, so a new-tab navigation
 * is enough for the browser to save it.
 */
export async function downloadAsset(assetId: string): Promise<void> {
  const url = await fetchAssetDownloadUrl(assetId);
  openDownloadUrl(url);
}

export async function fetchAssetDownloadUrl(assetId: string): Promise<string> {
  const asset = await api.get<Asset>(`/v1/assets/${assetId}`, { query: { download: true } });
  if (!asset.url) {
    throw new Error('Asset has no download URL.');
  }
  return asset.url;
}

export function openDownloadUrl(url: string): void {
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.target = '_blank';
  anchor.rel = 'noreferrer';
  anchor.click();
}
