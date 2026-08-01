# assets-pack

真实素材的投放目录。仓库里跑通链路用的是明确标记 `PROTOTYPE` 的临时占位图；真实素材到位后放进这里，一条命令即可整体替换，不需要改代码。

```text
assets-pack/
├─ manifest.json          # 你要写的清单（可从 manifest.example.json 复制）
├─ manifest.example.json  # 契约示例，随代码维护
├─ media/                 # 图片与视频本体
└─ consent/               # 涉及真人肖像时的授权证明
```

## 导入

```bash
make import-assets                       # 读取 assets-pack/manifest.json
python -m app.scripts.import_assets_pack --manifest ../assets-pack/manifest.json --dry-run
```

导入器会把文件上传到 MinIO、登记 `Asset`、写入 pHash 指纹与 AI 溯源清单。`replaces_prototype` 指向的占位素材会被替换成真实素材，引用它的作品版本无需改动。

## 字段约定

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `slug` | 是 | 包内唯一。重复导入时按 slug 幂等，不会产生重复素材。 |
| `file` | 是 | 相对 `assets-pack/` 的路径，必须在目录内。 |
| `mime_type` | 是 | 必须在服务端允许的上传类型白名单内。 |
| `role` | 是 | `generation_output` / `generation_reference` / `avatar` / `profile_cover`。 |
| `width` / `height` / `duration_ms` | 否 | 图片留空时由导入器从文件本身读取。 |
| `replaces_prototype` | 否 | 要替换的占位素材标记；留空则作为新素材登记。 |
| `license` / `attribution` | 否 | 未填时取 `defaults` 里的同名字段。 |
| `consent` | 涉及真人时必填 | 缺失会导致该条目被拒绝，而不是静默放行。 |
