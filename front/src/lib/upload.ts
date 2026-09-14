import { api } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';
import { sha256Hex } from '@/lib/sha256';

export { sha256Hex } from '@/lib/sha256';

type Presign = components['schemas']['UploadPresignResponse'];
export type Asset = components['schemas']['AssetResponse'];
export type Consent = components['schemas']['ConsentResponse'];
export type ConsentType = 'voice' | 'portrait';

/**
 * Three-step upload: presign, PUT straight to object storage, then register.
 *
 * The checksum is computed in the browser and signed into the URL, so the
 * backend can reject an object whose bytes do not match what was promised —
 * the upload never passes through the API server.
 */
export async function uploadFile(
  file: File,
  purpose:
    | 'generation_reference'
    | 'avatar'
    | 'profile_cover'
    | 'consent_evidence'
    | 'learn_media'
    | 'series_logo'
    | 'episode_preview'
    | 'video_analysis_source'
    | 'editor_source'
    | 'editor_export'
    | 'caption'
    | 'font'
    | 'voice_sample',
  options: {
    /** The uploader's declaration that an image/video shows a real person —
     * such a reference then needs a portrait consent (`declareConsent`)
     * before a generation job may use it. Ignored for other media. */
    depictsRealPerson?: boolean;
  } = {},
): Promise<Asset> {
  const checksum = await sha256Hex(await file.arrayBuffer());

  const presigned = await api.post<Presign>('/v1/uploads/presign', {
    filename: file.name,
    mime_type: file.type,
    size_bytes: file.size,
    checksum_sha256: checksum,
    purpose,
    depicts_real_person: options.depictsRealPerson ?? false,
  });

  const put = await fetch(presigned.upload_url, {
    method: 'PUT',
    headers: presigned.required_headers,
    body: file,
  });
  if (!put.ok) throw new Error(`upload failed with ${put.status}`);

  return api.post<Asset>('/v1/uploads/complete', {
    upload_session_id: presigned.upload_session_id,
  });
}

/**
 * Records that the real person whose voice or likeness an uploaded asset
 * carries has personally consented to its use (深度合成管理规定 §14). A
 * voice-clone sample, or a reference uploaded with `depictsRealPerson`, is
 * refused at submit (`ASSET_RIGHTS_REQUIRED`) until this exists.
 */
export function declareConsent(
  assetId: string,
  consent: { type: ConsentType; subject: string },
): Promise<Consent> {
  return api.post<Consent>(`/v1/assets/${assetId}/consents`, {
    consent_type: consent.type,
    subject_reference: consent.subject,
  });
}
