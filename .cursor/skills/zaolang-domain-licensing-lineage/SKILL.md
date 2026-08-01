---
name: zaolang-domain-licensing-lineage
description: 造浪的可见性与二创授权、许可快照、创作链 LineageEdge 与墓碑、发布八步事务。Use when changing visibility rules, remix authorisation, licence snapshots, lineage edges, tombstones, draft publishing, or the royalty/notification side effects of publishing.
disable-model-invocation: true
---

# 许可、创作链与发布事务

## 职责

回答三个问题并且只在这里回答：谁能看这个作品、谁能二创它、二创出来的东西挂在创作链的哪个位置。发布是把草稿变成作品的**单一事务**，八个步骤有严格顺序。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/domain/licensing/service.py` | `can_view` / `can_remix` / `assert_viewable` / `assert_remixable` / `capture_license_snapshot` / `LICENSE_PERMISSIONS` |
| `back/app/domain/lineage/service.py` | `create_edge` / `ancestors` / `descendants` / `build_tree` / `ancestor_author_ids` / `is_referenced_by_descendants` |
| `back/app/domain/publishing/service.py` | `create_draft` / `publish`（八步）/ `change_visibility` / `tombstone` |
| `back/app/models/enums.py` | `Visibility`（含 `allows_remix`）、`LifecycleStatus`、`LicenseType` |
| `back/app/api/v1/works.py`、`drafts.py` | 对外入口 |
| `back/tests/unit/test_licensing_invariants.py`、`test_lineage_invariants.py` | 不变量测试 |

## 不可破坏的不变量

1. **默认可见性是 `PUBLIC_VIEW_ONLY`**。只有 `PUBLIC_REMIXABLE` 允许他人二创（`Visibility.allows_remix`），作者对自己的作品不受限制。
2. **许可快照在创建草稿那一刻冻结**。`LicenseSnapshot` 记录当时的条款、原作者署名与 `snapshot_at`；上游后来改许可或转私密，**已存在的二创不受影响**，可见性变更只对未来生效。
3. **二创入口必须 `assert_remixable`**，不是只在前端隐藏按钮。直接打 API 的 `public_view_only` 作品必须 `LicenseNotRemixable`（403）。
4. **墓碑保留节点**：`tombstone` 只把 `lifecycle_status` 改成 `TOMBSTONED`，永不删行。被墓碑的作品不可直接查看，但**仍可通过创作链看到占位节点**，否则下游作品的来源会凭空消失。删除用户走匿名化而非删除，理由相同。
5. **`LineageEdge` 指向版本而不是作品**，并冻结 `parent_author_snapshot` 与 `license_snapshot_id`。作者改名后旧边显示的仍是当时的署名。
6. **发布八步的顺序不能重排**：① 复核来源仍可二创 ② 发布前安全审核 ③ 建 `Work` + 首个 `WorkVersion` ④ 资产转可读 + 打标签 ⑤ 建 `LineageEdge` 并 `remix_count += 1` ⑥ 写检索索引 ⑦ 结算回流分成 ⑧ 通知祖先作者。安全审核必须在建 `Work` 之前；创作链边必须在通知与分成之前。
7. **一份草稿只能发布一次**（`draft.published_work_id` 非空即 `Conflict`），且没有生成结果不能发布，未勾选权利确认不能发布。
8. **`WorkVersion` 是不可变的**：改标题描述要新开版本，不要 UPDATE 旧版本——`immutable_created_at` 就是这个语义的标记。

## 改造切入点

- **加一种可见性**：`Visibility` 加值 + `allows_remix` 分支 + `resolve_license_type` 映射 + 前端 `publish-form.tsx` 与三语文案。检索的 `_visible_works()` 过滤条件也要跟。
- **加一种许可类型**：`LicenseType` 加值 + `LICENSE_PERMISSIONS` 加权限矩阵。**存量快照不回填**，快照就是历史。
- **发布时多做一件事**：插进 `publish` 的对应步骤里，注意它整体在一个事务里——外部调用（对象存储、通知）失败会回滚整个发布，所以「尽力而为」的副作用（分成、通知）放最后并自行容错。
- **改创作链遍历**：`build_tree` 有 `max_depth`（默认 6），`ancestors` / `descendants` 都有层数上限，不要去掉——环虽然不该出现，但深链会打爆响应体。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_licensing_invariants.py tests/unit/test_lineage_invariants.py tests/integration/test_publish_flow.py -v
```

手工路径：用 `mizuki` 对 `linhai` 的 `public_view_only` 作品发二创请求，必须 403；对 `public_remixable` 的《潮汐之上》成功后，在作品页创作链里能看到新节点。
