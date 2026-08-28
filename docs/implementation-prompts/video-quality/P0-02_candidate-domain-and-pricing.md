# 实现视频多候选领域模型、报价和制品追踪

## 仓库与边界

- 目标仓库：`/Users/mac001/project/zaolangai/zaolang`
- 开始前阅读适用的 `AGENTS.md`、README、数据模型技能说明和现有任务/积分测试。
- 基于现有 `GenerationJob`、`ProviderAttempt`、`Asset`、工作流引擎和积分账本实现。
- PostgreSQL 是候选、质量报告引用、推荐结果、审核和积分的唯一事实源。
- 保持现有鉴权、上传、报价、积分预扣/结算、幂等、异步轮询、取消和发布语义。
- 不下载模型权重，不调用真实供应商，不执行 GPU 推理。
- 测试只能使用 fake provider 和固定结果。
- 保留当前工作树中的所有无关修改。

## 已确认的源码事实

- 当前 H3 通过 `AiHubMixMediaProvider` 异步提交和轮询。
- H3 请求支持 4–15 秒、2K、首尾帧和图片/视频参考。
- 当前供应商请求不发送 `negative_prompt`，不得添加未经验证的 H3 请求字段。
- 当前 `quality_check` 只读取宽高、时长和供应商元数据，不能判断实际画面。
- 剧本 `breakpoint` 已经能携带片段文本、关联角色和场景进入视频工作室。
- 角色库已有参考图、声音描述和动作片段；场景库已有参考素材。
- 当前质量档为 `preview`、`standard`、`cinematic`。
- 当前生产容器没有 GPU 模型运行环境，独立模型必须通过硬件无关服务协议接入。

## 本任务相关补充事实

- 当前视频工作流一次只保留一个生成结果。
- `output_asset_ids_json` 当前主要服务角色多视角图片输出。
- `route_attempts` 同时承担供应商失败和质量重试预算，不适合作为候选循环计数。
- 视频供应商任务可异步暂停，并通过 `AsyncProviderTask` 恢复工作流。
- 当前质量档固定为 `preview`、`standard`、`cinematic`。
- 当前生成前预扣积分，成功后捕获实际积分，失败或取消释放余额。

## 目标

让同一视频镜头按照质量档生成 1/2/3 个可追踪候选，同时保持现有异步、积分、幂等、来源链和角色多视角行为兼容。

## 必须实现

1. 服务端固定候选数：
   - `preview = 1`；
   - `standard = 2`；
   - `cinematic = 3`。
   客户端不能绕过该上限，管理员自定义工作流只能降低、不能提高平台硬上限。
2. 新增 `GenerationCandidate` 持久化模型和迁移，至少保存：
   - `job_id`、`asset_id`、`parent_candidate_id`；
   - 候选序号和 `variant_type`；
   - base seed、实际 seed、供应商和模型/工作流版本；
   - 质量报告 JSON 或报告引用；
   - 自动推荐标志、可用状态、失败原因和时间戳。
3. `variant_type` 至少预留 `base`、`repair`、`face_enhanced`、`temporal_restored`，但本任务只实际生成 `base`。
4. 基础种子由服务端规范化；候选种子为 `base_seed + candidate_index`，处理整数上限并保证重放稳定。
5. 明确分离三类预算：
   - 候选循环；
   - 单候选供应商失败重试；
   - 后续修复重试。
   不再让它们共享一个 `route_attempts` 计数器。
6. 生成循环必须串行兼容当前“一项异步任务/作业”的恢复约束；不能在一个作业中创建无法恢复的并行外部任务。
7. 部分成功策略：达到至少 1 个合格候选时进入后续排序；全部失败才按现有失败路径结算。
8. 扩展 `output_asset_ids_json` 的正式语义以支持视频候选，同时保持旧角色三视图顺序和响应兼容。
9. `output_asset_id` 在任务结算时指向自动推荐候选；其他成功候选保持私有、可追溯且不会自动发布。
10. 报价按候选上限计算最大预扣；实际结算按真正发生的生成尝试和配置价格计算，不能重复捕获或超过 `max_credits`。
11. 清理策略必须区分临时候选与已审核、已发布、已进入编辑器或被来源链引用的资产；后四类不得自动清理。
12. 所有候选写入完整生成来源，不得用复制资产的方式丢失供应商尝试和父候选关系。

## 建议检查的源码入口

- `back/app/models/generation.py`
- `back/app/models/async_tasks.py`
- `back/app/domain/credits/pricing.py`
- `back/app/domain/jobs/service.py`
- `back/app/workflows/nodes.py`
- `back/app/workers/async_polling.py`
- `back/app/api/schemas/jobs.py`

## 测试与验收

- 三个质量档分别产生 1/2/3 个基础候选。
- 相同基础种子的候选 seed 稳定且不重复。
- 第二、第三候选异步暂停后能从正确候选索引恢复。
- 单候选供应商失败不会覆盖已成功候选，也不会错误排除可继续使用的供应商。
- 幂等重放不新增候选、不重复预扣和结算。
- 部分成功、全部失败、取消、超时和超过预算均有确定结果。
- `output_asset_id`、`output_asset_ids_json`、角色多视角图片和旧 API 响应零回归。
- 迁移升级、降级或明确不可降级策略经过测试和说明。

## 非目标

- 不实现真实视频质量分析、候选评分或人工审核界面。
- 不接入 VACE、GFPGAN、BasicVSR++ 或 Wan-Animate。
- 不并行提交多个外部视频任务。

## 最终交付

最终答复必须列出数据迁移、领域模型、报价变化、异步恢复行为、实际测试、未验证项和关键文件绝对路径。不要将候选数量增加描述成质量已经提升。
