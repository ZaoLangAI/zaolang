import { api } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

type Presign = components['schemas']['UploadPresignResponse'];
export type Asset = components['schemas']['AssetResponse'];

/**
 * Three-step upload: presign, PUT straight to object storage, then register.
 *
 * The checksum is computed in the browser and signed into the URL, so the
 * backend can reject an object whose bytes do not match what was promised —
 * the upload never passes through the API server.
 */
export async function uploadFile(
  file: File,
  purpose: 'generation_reference' | 'avatar' | 'profile_cover' | 'consent_evidence' | 'learn_media',
): Promise<Asset> {
  const checksum = await sha256Hex(await file.arrayBuffer());

  const presigned = await api.post<Presign>('/v1/uploads/presign', {
    filename: file.name,
    mime_type: file.type,
    size_bytes: file.size,
    checksum_sha256: checksum,
    purpose,
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

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}
