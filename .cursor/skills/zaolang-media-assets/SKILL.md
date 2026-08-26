---
name: zaolang-media-assets
description: The upload pipeline and content integrity — MinIO presigned uploads and complete, MIME/size/prefix constraints, Asset roles and private-object signed downloads, pHash fingerprint dedup and reuse detection, AI-generation provenance manifests, assets-pack import. Use when changing uploads, presigned URLs, object keys, asset visibility, media probing, perceptual hashing, provenance manifests, or the assets-pack import script.
disable-model-invocation: true
---

# Upload Pipeline & Content Integrity

## Scope

Ensure what goes into the bucket is something we allow, that what comes out of it is something the caller is authorized to see, and that the system can answer "do we already have this file" and "how was this video generated."

## Key Paths

| File | Contents |
| --- | --- |
| `back/app/domain/media/service.py` | `presign_upload` / `complete_upload` / `register_generated_asset` / `record_provenance` / `record_fingerprint` / `find_near_duplicates` / `signed_url_for` / `publish_asset` / `list_owned_media` (the editor's media-library query — `GENERATION_OUTPUT`/`EDITOR_SOURCE` roles only) |
| `back/app/storage/s3.py` | `ALLOWED_UPLOAD_MIME_TYPES`, `MAX_UPLOAD_BYTES`, `PURPOSE_PREFIXES` (incl. `editor_source` / `editor_export`), presigning, bucket CORS and lifecycle policy |
| `back/app/api/v1/uploads.py` | `POST /v1/uploads/presign` and `POST /v1/uploads/complete`; `GET /assets:mine` (the drama editor's media-library listing — see `zaolang-editor-drama`) |
| `back/app/presenters/media_urls.py` | outbound URL assembly (signing and expiry) |
| `back/app/scripts/import_assets_pack.py` | reads a local `assets-pack/manifest.json` under the `assets-pack/manifest.example.json` contract; supports import and `--dry-run` validation |
| `front/src/lib/upload.ts`, `front/src/components/studio/source-material-rail.tsx` | the frontend's two-phase upload |

## Invariants

1. **Uploads are two-phase**: first `presign` (server validates MIME, size cap, and purpose), the client uploads directly to MinIO, then `complete` (server re-verifies the actual object, probes dimensions/duration, creates the `Asset`). **An object without a `complete` call is not an asset** and is cleaned up by lifecycle policy.
2. **Whitelist constraints apply before a presigned URL is issued**: only `image/png` / `image/jpeg` / `image/webp` / `video/mp4` / `video/webm` are allowed; size caps vary by purpose (reference image 32MB, avatar 4MB, cover 12MB, authorization evidence 16MB, editor source/export 256MB).
3. **Every purpose is confined to its own prefix** (`PURPOSE_PREFIXES`, all under `staging/`) — an avatar's signed URL can't be replayed to overwrite a generated output. `editor_export`'s `complete` requires HEAD + checksum + **ffprobe**. Editor-source duration/dimension analysis is `MediaAnalysis` + the `media_analysis` queue, owned by `zaolang-editor-drama` — don't put ffprobe analysis logic in `media/service.py`. The same table/queue also carries ASR subtitle transcription now, as a second analyzer identity (`ASR_ANALYZER = "whisper-asr"`) — same "owned by `zaolang-editor-drama`, don't duplicate in `media/service.py`" rule applies to it too.
4. **Private objects are downloadable only via short-lived signed URLs**, and the caller's permission on that asset must be checked before signing. The bucket is never public — don't set an object `public-read` for convenience.
5. **`publish_asset` runs only at publish time**: it moves the object from staging into the readable area. A rolled-back publish transaction must not leave a publicly readable object behind.
6. **pHash is stored as the string form of a signed 64-bit integer** (`_to_signed_64`); comparison uses Hamming distance with threshold `DUPLICATE_HAMMING_THRESHOLD = 6`. Changing the threshold changes both "block duplicate uploads" and the admin "duplicate fingerprints" view at once.
7. **AI-generated output must carry a provenance manifest** (`ProvenanceManifest`: model, parameters, source assets, timestamp). C2PA signing is a reserved interface slot — don't claim it's implemented.
8. **`AssetConsent`**: consent evidence for material involving real likenesses is stored separately from the asset itself, with a tracked status history.
9. **Generation reference assets resolve by user ownership**: a normal H3 reference accepts up to 9 images/videos; first/last-frame mode accepts images only and is mutually exclusive with normal references. Providers only ever receive short-lived signed URLs generated from object keys — never an arbitrary user-supplied external URL.

## Extension Points

- **Allow a new format**: add an entry to `ALLOWED_UPLOAD_MIME_TYPES` (with its extension) → add a probing branch to `_probe` (reject if dimensions/duration can't be read) → update the frontend `accept` attribute and copy → add coverage in `tests/unit/test_media_integrity.py`.
- **Add a purpose**: `MAX_UPLOAD_BYTES` and `PURPOSE_PREFIXES` must be added together — missing either raises a `KeyError` at presign time.
- **Change fingerprinting**: `record_fingerprint` and `find_near_duplicates` change together; existing fingerprints don't auto-recompute — write a one-off backfill script.
- **Swap object storage**: `app/storage/s3.py` is a thin facade over whichever `StorageBackend` `STORAGE_BACKEND` selects (`app/storage/factory.py`) — MinIO (`app/storage/backends/minio.py`, boto3) or Tencent COS (`app/storage/backends/tencent_cos.py`, `cos-python-sdk-v5`). The domain layer only ever imports `app.storage.s3` and stays unaware which backend is active. Lifecycle policy and usage stats are part of the `StorageBackend` interface (`app/storage/base.py`) and are implemented by both backends. Add a third backend by implementing `StorageBackend` and adding a branch in `factory.get_backend()` — no facade or call-site changes needed.

## Assets Pack

`assets-pack/manifest.example.json` is the versioned contract example; once real assets are ready, copy it to a local `assets-pack/manifest.json` and fill it in — this file is not checked into the repo. `make check-assets` validates only, without writing; `make import-assets` actually persists. Before real assets are ready, seed data uses temporary media explicitly marked `PROTOTYPE`, and **visual acceptance cannot be declared passed** until real assets are in place.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_media_integrity.py tests/unit/test_assets_pack_import.py -v
make check-assets
```

Manual path: upload a reference image on `/create` → the active backend's console (MinIO `localhost:9001` if `STORAGE_BACKEND=minio`, the Tencent COS console if `tencent_cos`) should show exactly one object under the matching prefix → accessing that object URL while logged out must fail.
