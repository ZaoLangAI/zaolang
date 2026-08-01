---
name: zaolang-media-assets
description: 造浪的上传链路与内容完整性：MinIO 预签名上传与 complete、MIME/大小/前缀约束、Asset role 与私密对象签名下载、pHash 指纹去重与洗稿检测、AI 生成溯源清单、assets-pack 导入。Use when changing uploads, presigned URLs, object keys, asset visibility, media probing, perceptual hashing, provenance manifests, or the assets-pack import script.
disable-model-invocation: true
---

# 上传链路与内容完整性

## 职责

保证进桶的东西是我们允许的、出桶的东西是调用者有权看的，并且能回答「这个文件是不是已经有了」「这段视频是怎么生成的」。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/domain/media/service.py` | `presign_upload` / `complete_upload` / `register_generated_asset` / `record_provenance` / `record_fingerprint` / `find_near_duplicates` / `signed_url_for` / `publish_asset` |
| `back/app/storage/s3.py` | `ALLOWED_UPLOAD_MIME_TYPES`、`MAX_UPLOAD_BYTES`、`PURPOSE_PREFIXES`、预签名与生命周期策略 |
| `back/app/api/v1/uploads.py` | `POST /v1/uploads/presign` 与 `POST /v1/uploads/complete` |
| `back/app/presenters/media_urls.py` | 出站 URL 组装（签名与有效期） |
| `back/app/scripts/import_assets_pack.py` | `assets-pack/manifest.json` 导入与 `--dry-run` 校验 |
| `front/src/lib/upload.ts`、`front/src/components/studio/source-material-rail.tsx` | 前端两段式上传 |

## 不可破坏的不变量

1. **上传是两段式**：先 `presign`（服务端校验 MIME、大小上限、用途），客户端直传 MinIO，再 `complete`（服务端复核实际对象、探测尺寸与时长、建 `Asset`）。**没有 `complete` 的对象不是资产**，靠生命周期策略清理。
2. **白名单约束在发预签名之前生效**：只允许 `image/png` / `image/jpeg` / `image/webp` / `video/mp4` / `video/webm`；大小上限按用途区分（参考图 32MB、头像 4MB、封面 12MB、授权证据 16MB）。
3. **每种用途关进自己的前缀**（`PURPOSE_PREFIXES` 全部在 `staging/` 下）。这样一个头像的签名 URL 无法被重放去覆盖生成产物。
4. **私密对象只能通过短时效签名 URL 下载**，且签发前必须校验调用者对该资产的权限。桶不对公网开放，不要为了省事把对象设成 public-read。
5. **发布时才 `publish_asset`**：把对象从 staging 迁到可读区。发布事务回滚时不能留下已公开的对象。
6. **pHash 存 64 位有符号整数的字符串形式**（`_to_signed_64`），比较用汉明距离，阈值 `DUPLICATE_HAMMING_THRESHOLD = 6`。改阈值会同时改变「重复上传拦截」与后台「指纹重复项」两处行为。
7. **AI 生成产物必须有溯源清单**（`ProvenanceManifest`：模型、参数、来源资产、时间）。C2PA 签名是预留接口位，不要声称已实现。
8. **`AssetConsent`**：涉及真人肖像等素材的授权证据与资产分离存储，状态流转要留痕。

## 改造切入点

- **允许一种新格式**：`ALLOWED_UPLOAD_MIME_TYPES` 加项（带扩展名）→ `_probe` 加探测分支（拿不到尺寸/时长就别接受）→ 前端 `accept` 属性与文案 → 补 `tests/unit/test_media_integrity.py`。
- **加一种用途**：`MAX_UPLOAD_BYTES` 与 `PURPOSE_PREFIXES` 必须成对加，缺一会在预签名时 KeyError。
- **改指纹策略**：`record_fingerprint` 与 `find_near_duplicates` 成对改；存量指纹不会自动重算，要写一次性脚本。
- **换对象存储**：只改 `app/storage/s3.py`（boto3 S3 兼容层），领域层不感知。生命周期策略与用量统计也在这里。

## 素材包

`assets-pack/manifest.json` 是与用户约定的契约：`make check-assets` 只校验不写库，`make import-assets` 才落库。真实素材未到位前，种子里用明确标记 `PROTOTYPE` 的临时媒体，**视觉验收在真实素材到位前不能宣布通过**。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_media_integrity.py tests/unit/test_assets_pack_import.py -v
make check-assets
```

手工路径：`/create` 上传一张参考图 → MinIO 控制台（`localhost:9001`）应只在对应前缀下出现一个对象 → 未登录直接访问该对象 URL 必须失败。
