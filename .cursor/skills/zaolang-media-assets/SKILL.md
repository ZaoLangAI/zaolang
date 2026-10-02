---
name: zaolang-media-assets
description: Upload pipeline and asset integrity — presign/complete, purpose prefixes, MIME/size limits, reference-video conform, private signed downloads, pHash, provenance, consent, storage backends, assets-pack import. Use when changing uploads, object keys, asset visibility, signed URLs or storage.
---

# Upload Pipeline & Asset Integrity

**Scope**: what enters the bucket, who may read it back, fingerprints and AI provenance.
Not here → `zaolang-editor-drama` (media analysis/ASR, episode previews, `/v1/assets:mine`), `zaolang-generation-jobs` (references in jobs).

## Key Paths

| Path | What |
|---|---|
| `back/app/storage/s3.py` | Facade over the active `StorageBackend` (callers never import a backend): whitelists, presign, lifecycle |
| `back/app/storage/factory.py` | `get_backend` → MinIO or Tencent COS by `Settings.storage_backend` (`back/app/storage/backends/`); ABC in `back/app/storage/base.py`; `back/app/storage/cors.py:merge_cors_origins` |
| `back/app/domain/media/service.py` | presign/complete, reference checks, `signed_url_for`, `publish_asset`, pHash, provenance, `delete_exclusive_assets` |
| `back/app/domain/media/conform.py` | `conform_reference_video` → H.264/yuv420p CFR `+faststart` MP4 |
| `back/app/domain/consent/service.py` | `assert_reference_consents` (voice / portrait) |
| `back/app/api/v1/uploads.py` | presign, complete, `GET /v1/assets/{id}`, frame, provenance, consents |
| `back/app/presenters/media_urls.py` | `asset_url` (signing), `asset_duration_ms` |
| `back/app/scripts/import_assets_pack.py` | assets-pack import; contract `assets-pack/manifest.example.json` |
| `front/src/lib/upload.ts` | `uploadFile`: sha256 → presign → PUT → complete; `declareConsent` (admin `style_gallery_cover`: `front/src/lib/admin/upload.ts`) |
| `front/src/lib/sha256.ts`, `front/src/lib/random-id.ts` | SHA-256 / UUID fallbacks for plain-HTTP origins |
| `front/src/lib/download-asset.ts` | Save-as: `?download=true` → open attachment URL in new tab |
| `front/src/lib/refresh-media-src.ts` | Re-fetch expired signed URLs (asset, job, work, draft) |

## Invariants

1. Two-phase: presign checks MIME/size/purpose; browser PUTs to the store; `complete` re-checks HEAD + checksum and creates the `Asset`. No `complete` → no asset.
2. Upload purposes (fourteen purposes in `back/app/storage/s3.py:PURPOSE_PREFIXES`, own `staging/` prefix each, caps in `MAX_UPLOAD_BYTES`): `generation_reference`, `avatar`, `profile_cover`, `consent_evidence`, `learn_media`, `style_gallery_cover`, `series_logo`, `episode_preview`, `editor_source`, `editor_export`, `caption`, `font`, `video_analysis_source`, `voice_sample`. MIME: `image/png`, `image/jpeg`, `image/webp`, `video/mp4`, `video/webm`, `audio/mpeg`, `audio/wav`. `back/tests/unit/test_skill_freshness.py` enforces both lists here.
3. `presign_upload`: avatar/cover/style-gallery/logo/preview/learn purposes image-only, `video_analysis_source` video-only (≤3 min, `VIDEO_ANALYSIS_MAX_DURATION_MS`, checked at job submit), `voice_sample` audio-only. Key `{prefix}/{owner_id}/{obj id}{ext}`.
4. `generation_reference` videos are conformed on complete only if container, codec, pix_fmt, fps (23.98–60) or duration would be refused; the `.mp4` replaces the original key, size, checksum. No ffmpeg → original kept.
5. Private bucket. `signed_url_for` allows owner, `viewer_is_staff` (no consumer route passes it — a consumer session's admin role never counts) or non-`PRIVATE`, else 404 (never 403). `media_urls.asset_url` signs without checking — call it only after an access decision. Playback URLs stay inline; Save-as mints `Content-Disposition: attachment` (`download_filename_for`). No `<a download>`, no blob fetch.
6. `publish_asset` only flips visibility to `PUBLIC_VIEW_ONLY` in the publish transaction — no object move.
7. `delete_exclusive_assets` skips shared assets — including any image filed on a character/scene card (`SkillAssetEntry`); a new pointer column at `Asset` needs an `_is_shared` branch.
8. References: owner, the remixable source output, or a published skill cover (`_asset_is_usable_reference`). Providers get signed URLs only. Voice samples need `voice` consent, `depicts_real_person` refs `portrait` consent, else 422.
9. pHash in `ContentFingerprint.fingerprint_hex` + `fingerprint_bits`, images only. `find_near_duplicates` (Hamming ≤ 6) has no prod caller; admin duplicates group exact hex.
10. `record_provenance` → `ProvenanceManifest` on generated outputs, editor exports and assets-pack imports; C2PA signing not implemented.
11. Signed URLs live `download_url_ttl_seconds` (900s; PUT `upload_url_ttl_seconds` 600s, `back/app/config.py`). Never persist or cache them — store asset ids and re-sign per request; Next data-cache rule: `zaolang-frontend-ui`.
12. One bucket may serve laptop and prod: `ensure_bucket` unions `cors_origins` into the existing rule (`merge_cors_origins`), never replaces it.

## Recipes

**Add a purpose**: `MAX_UPLOAD_BYTES` + `PURPOSE_PREFIXES` together → `PURPOSE_TO_ROLE` → MIME gate → `UploadPresignRequest.purpose` regex (`back/app/api/schemas/jobs.py`) → `uploadFile` union → purpose list above.

**Allow a MIME**: `ALLOWED_UPLOAD_MIME_TYPES` → `_probe` → front `accept` → `back/tests/unit/test_media_integrity.py` → MIME list above.

**Add a backend**: implement `StorageBackend` (incl. `presign_get(download_name=)`) → branch in `get_backend`.

**Assets pack**: copy the example to a local manifest.json → `make check-assets` (dry run) → `make import-assets`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_media_integrity.py tests/unit/test_reference_video_conform.py tests/unit/test_voice_consent.py tests/unit/test_storage_cors.py tests/unit/test_storage_backend_selection.py tests/unit/test_assets_pack_import.py tests/unit/test_skill_freshness.py -v
make check-assets
# expiry repro: DOWNLOAD_URL_TTL_SECONDS=60 make dev-api; rm -rf front/.next/cache/images first (COS back-dates signatures 60s)
```
