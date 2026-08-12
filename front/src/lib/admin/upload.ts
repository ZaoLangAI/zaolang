import { adminApi } from '@/lib/api/admin-client';
import type { components } from '@/lib/api/schema';

type Presign = components['schemas']['UploadPresignResponse'];
export type AdminAsset = components['schemas']['AssetResponse'];

/**
 * Cover art for a style gallery entry.
 *
 * Mirrors `lib/upload.ts`'s presign/PUT/complete dance, against the
 * admin-only `/v1/admin/style-gallery/uploads/*` pair instead of the
 * consumer one — the cover is operator-supplied art, not a generation
 * output, so it never goes through the consumer's own asset endpoints.
 */
export async function uploadStyleGalleryCover(file: File): Promise<AdminAsset> {
  const checksum = await sha256Hex(await file.arrayBuffer());

  const presigned = await adminApi.post<Presign>('/v1/admin/style-gallery/uploads/presign', {
    filename: file.name,
    mime_type: file.type,
    size_bytes: file.size,
    checksum_sha256: checksum,
    purpose: 'style_gallery_cover',
  });

  const put = await fetch(presigned.upload_url, {
    method: 'PUT',
    headers: presigned.required_headers,
    body: file,
  });
  if (!put.ok) throw new Error(`upload failed with ${put.status}`);

  return adminApi.post<AdminAsset>('/v1/admin/style-gallery/uploads/complete', {
    upload_session_id: presigned.upload_session_id,
  });
}

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}
