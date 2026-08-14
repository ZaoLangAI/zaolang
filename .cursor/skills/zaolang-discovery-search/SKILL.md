---
name: zaolang-discovery-search
description: 造浪的发现与复用：可插拔 EmbeddingProvider + pgvector 相似作品、关键词与语义混合检索、标签体系、发现页灵感墙排序（recent/popular/remixed）、用户 StylePreset 与平台策展 StyleGalleryEntry。Use when changing search, browse feeds, tag filters, inspiration-wall sort, embeddings, vector similarity, style presets, or the system style gallery.
disable-model-invocation: true
---

# 发现与复用

## 职责

让作品被找到（浏览、搜索、相似推荐），让参数被复用（标签、用户风格预设、系统画风库）。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/domain/search/service.py` | `browse` / `search` / `similar_works` / `index_version` / `_visible_works` |
| `back/app/domain/search/embeddings.py` | `EmbeddingProvider` 抽象、`DeterministicEmbeddingProvider`、`get_provider` / `set_provider` / `embed` |
| `back/app/models/search.py` | `WorkEmbedding`（pgvector `Vector` 列） |
| `back/app/models/works.py` | `Tag` / `WorkTag` / `StylePreset`（用户从作品蒸馏的快捷参数，可公开分享） |
| `back/app/models/style_gallery.py` | `StyleGalleryEntry`（平台策展系统画风，后台 Operator 写，C 端灵感墙与工作室弹窗共用） |
| `back/app/api/v1/works.py` | 浏览与搜索接口 |
| `back/app/api/v1/style_gallery.py` | 公开画风列表 / 详情 / `/apply` 计数 |
| `front/src/app/[locale]/(site)/discover/page.tsx`、`front/src/components/discover/tag-filter.tsx` | 首页 `/` 重定向到发现页；灵感墙 `TagFilter` + `DiscoverSort`（`recent`/`popular`/`remixed`，URL `?sort=`） |
| `front/src/components/work/reusable-params.tsx` | 参数一键套用 |
| `front/src/components/studio/style-gallery-dialog.tsx`、`front/src/components/create/inspiration-recommendations.tsx` | 系统画风套用；job 提交 `style_gallery_id`，由 `skill_context` 服务端再折 `prompt_suffix` |

## 不可破坏的不变量

1. **可见性过滤在 SQL 层**：所有检索必须从 `_visible_works()` 出发（只含 `ACTIVE` 且非 `PRIVATE`）。**不要先查后过滤**——分页会把被过滤掉的行算进页大小，泄露存在性也泄露总量。
2. **墓碑与隐藏作品不进检索结果**，但仍可通过创作链访问（见 `zaolang-domain-licensing-lineage`）。
3. **`EmbeddingProvider` 保持可插拔**：网关**没有 embedding 模型**，默认实现是本地确定性哈希向量。它的意义是「接口与链路可用」，不是「检索质量达标」——交付报告里如实标注。测试通过 `set_provider` 注入，不要在领域代码里 `import` 具体实现。
4. **向量维度改变是破坏性变更**：`WorkEmbedding` 的列维度、迁移、以及所有存量行必须一起重算，没有渐进路径。
5. **混合检索的顺序固定**：关键词命中优先，语义补充，去重后合并；不要让语义结果把精确标题匹配挤下去。
6. **发布时同步写索引**：`index_version` 是发布八步中的第 6 步，漏掉就等于新作品搜不到。
7. **标签是规范化实体**：`Tag` 唯一，`WorkTag` 关联。不要把标签存成作品上的字符串数组。
8. **发现页 Hero 不跟墙的 sort 走**：墙用 `?sort=`（缺省 `popular`，默认值不写进 URL）；Hero 固定 `popular`，避免「本期精选」变成最新。仅当两边同一有效查询（有 `q`，或无 `q` 且 `sort=popular`）才从墙去掉精选前 6 条。`recent`/`remixed` 墙展示完整第一页。创作页灵感墙是系统画风库、按 `sort_order`，不要混进这条。iOS 三档相同，但墙默认是 `recent`。

## 改造切入点

- **换真实向量模型**：实现 `EmbeddingProvider` 子类 → `set_provider` 注册（或按配置选择）→ 处理维度变更迁移 → 重算全部 `WorkEmbedding`。领域与 API 层不需要改。
- **加一个排序维度**：改 `browse` 的排序键（游标要求**稳定且唯一**，末位加 `id` 兜底）→ `GET /v1/works?sort=` → Web `DiscoverSort` chip 与 iOS `WorksSort` 菜单（三语 `discover.sort*`）。Web 筛选/排序必须可分享（走 URL）。
- **加一种筛选**：过滤条件 → 接口参数 → `TagFilter` / `DiscoverSort` 与 URL query 同步；无标签时排序条仍要渲染。
- **扩展风格预设**：`StylePreset` 的 `params_json` 结构与生成参数同源，加字段要同时改「保存预设」与「套用预设」两条路径。系统画风 `StyleGalleryEntry` 是另一张表、另一套后台 CRUD，不要把运营目录写进用户预设；任务身份字段是 `style_gallery_id`，不要复用死字段 `style_preset_id`。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_discovery.py -v
```

手工路径：`/discover` 搜索「潮汐」应命中种子作品；切「最新」后 URL 含 `sort=recent`、精选仍偏热门；作品页「相似作品」不为空；给作品加标签后按标签筛选能命中；把作品转为私密后立刻从检索中消失。
