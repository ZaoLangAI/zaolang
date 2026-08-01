---
name: zaolang-lineage-graph
description: 造浪的创作链图谱前端：dagre 布局 + 自绘 SVG 的树状 DAG、双向溯源（从何而来 / 被谁继续创作）、墓碑节点、父子版本参数差异对比面板。Use when changing the lineage graph, its layout, tombstone rendering, node interaction, or the version parameter diff panel.
disable-model-invocation: true
---

# 创作链图谱

## 职责

一屏之内让人看懂「这个作品从哪来、被谁继续创作」。树状 DAG 与双向溯源（从何而来 / 被谁继续创作）是完整实现，不是可选增强。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `front/src/components/lineage/lineage-graph.tsx` | dagre 布局 + 自绘 SVG，`NODE_WIDTH/HEIGHT`、`GraphNode.direction`（`ancestor` / `root` / `descendant`） |
| `front/src/components/lineage/lineage-dialog.tsx` | 全屏查看容器 |
| `front/src/components/lineage/version-diff-panel.tsx` | 父子版本参数差异 |
| `front/src/components/work/lineage-strip.tsx` | 作品页里的紧凑入口 |
| `back/app/domain/lineage/service.py` | `build_tree` / `ancestors` / `descendants`，数据来源 |
| `front/src/lib/api/types.ts` | `LineageNode` / `LineageResponse` |

## 不可破坏的不变量

1. **布局用 dagre 计算，渲染自绘 SVG**。不引图可视化库：节点必须消费与页面同一套主题令牌（见 `zaolang-theming`），canvas 方案既不跟主题也不可键盘访问。
2. **双向同时展示**：祖先在一侧、后代在另一侧，当前作品是 `root` 且视觉上可辨。只画一个方向就退回成了「来源列表」，不是图谱。
3. **墓碑节点必须显示为占位而不是消失**（`tombstone: true` + `IconTombstone`），并且不可点进详情。下游作品的来源不能凭空断掉——这是后端墓碑保留的前端另一半。
4. **节点键盘可达**：Tab 能遍历、Enter/Space 能选中、焦点环可见。图谱是交互组件不是插图。
5. **深度有上限**：后端 `build_tree` 默认 `max_depth=6`。前端不要自己递归展开到无限层，深链会打爆 SVG 与响应体。
6. **参数 diff 只对比同一条边的父子两侧**，展示的是 `reusable_params_json` 的差异；缺字段与值变化要能区分（新增 / 删除 / 修改三态）。
7. **图谱是只读视图**：从这里发起二创要走正常的 `assert_remixable` 授权路径，不要因为节点可见就假设可二创。

## 改造切入点

- **改布局**：调 dagre 的 `rankdir` / 间距常量与 `NODE_WIDTH` / `NODE_HEIGHT`；改完必须在三个视口下检查无横向溢出（视觉套件会查）。
- **加节点信息**：先扩后端 `LineageNode`（`app/domain/lineage/service.py`）→ `make openapi` → 前端类型自动跟上 → 节点尺寸常量可能要一起调。
- **加一种节点状态**（例如「审核中」）：`direction` 与 `tombstone` 之外新增字段，不要复用 `tombstone` 表达其他含义。
- **性能**：节点数大时先在后端截断并给出「还有 N 个」的提示，不要在前端做虚拟化——这是图不是列表。

## 验证

```bash
make test-front
make test-a11y && make qa-visual
```

手工路径：打开种子作品《潮汐之上》的作品页 → 图谱能看到二创《潮汐之上 · 夜行》与被墓碑的那条分支 → 点两个相邻版本，diff 面板给出参数差异。
