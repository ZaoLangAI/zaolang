# 实现硬件无关媒体分析与处理器协议

## 仓库与边界

- 目标仓库：`/Users/mac001/project/zaolangai/zaolang`
- 开始前阅读适用的 `AGENTS.md`、README、供应商配置、异步任务和安全测试。
- 不把 PyTorch、CUDA、OpenVINO、DWPose、VACE 等模型依赖安装到主 API 容器。
- 浏览器不得直连媒体处理服务、供应商或裸 ComfyUI。
- PostgreSQL 保持为任务、端点配置、审计和结果的唯一事实源。
- 不下载权重，不调用真实外部服务，不执行 GPU 推理。
- 使用 fake analyzer/processor 验证协议和异步恢复。
- 保留当前 H3 生成路径和所有无关用户改动。

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

- `GenerationProvider` 当前面向图片、视频和音频生成。
- 视频生成支持异步 `submit`、`poll`、`cancel` 和工作流检查点恢复。
- 当前媒体端点由后台模型配置和能力路由构建。
- `comfyui` 协议已出现在枚举中，但仍属于未实现协议，不能假装可用。
- 当前生产 Compose 没有 GPU 模型服务。
- `Series.allow_external_models` 已存在，但尚未完整约束新增处理器的数据外发。

## 目标

为本地轻量分析模型和外部 GPU 修复服务提供统一、可验证、硬件无关的异步协议，同时保持生成供应商接口职责清晰。

## 必须实现

1. 定义与 `GenerationProvider` 分离的抽象：
   - `VideoAnalyzerProvider`；
   - `VideoProcessorProvider`。
2. 定义稳定任务种类：
   - `analyze`；
   - `face_enhance`；
   - `temporal_restore`；
   - `masked_repair`。
3. 两类接口支持 `submit`、`poll`、`cancel`，同步完成和异步完成必须使用同一结果类型表达。
4. 输入只能包含：
   - 已授权的短期签名媒体 URL；
   - 参考资产 URL；
   - 结构化任务参数；
   - 任务、候选和剧集的不可伪造标识。
   不得包含本地路径、对象存储密钥或其他供应商凭据。
5. 分析输出为结构化报告；处理输出为新媒体制品及其技术元数据。不得允许处理服务直接写平台数据库。
6. 扩展现有异步任务模型或提供兼容抽象，记录 `task_kind`、适配器类型、能力、请求快照和恢复节点；已有生成任务无需数据回填也能继续轮询。
7. 后台模型管理增加独立的“媒体处理器”域，而不是把处理器伪装成普通 LLM：
   - 服务地址、能力、版本、revision；
   - 许可证和验证状态；
   - 超时、并发、价格；
   - 是否接收人脸、视频或声音素材；
   - 本地/外部处理标志。
8. 落实剧集 `allow_external_models`：
   - `false` 时保留既有 H3 生成路径，但禁止新增外部分析、增强和替代模型接收素材；
   - `true` 时也只允许后台已启用、许可证与验证状态合格的处理器；
   - 本地处理器不受外发开关限制，但仍需登记制品版本。
9. 审计外发的剧集、作业、候选、资产、端点和用途；任何审计记录都不得保存签名 URL、Authorization header 或 API key。
10. 未验证、许可证缺失、能力不匹配、剧集未授权或端点被禁用时 fail closed，并返回可支持的内部错误码和用户友好消息。
11. 处理器配置应位于业务模型/媒体处理管理页面，不把密钥重新塞回通用 `/admin/config`。

## 建议检查的源码入口

- `back/app/providers/base.py`
- `back/app/providers/media_endpoints.py`
- `back/app/models/async_tasks.py`
- `back/app/workers/async_polling.py`
- `back/app/platform_config/schemas.py`
- `back/app/api/v1/admin/llm_providers.py`
- 对应管理前端和供应商连接测试。

## 测试与验收

- 本地 fake analyzer 同步完成并返回结构化报告。
- 外部 fake processor 异步提交、重复 poll、完成、失败、超时和取消。
- 老的 H3 异步任务快照可继续恢复。
- 未授权剧集拒绝新增外部服务，但当前 H3 路径不受影响。
- 本地处理器在未授权剧集仍可运行。
- 禁用、未验证、许可证为空和能力不匹配端点不能进入调度。
- 审计和日志扫描确认不含签名 URL、密钥和内部路径。
- 管理端点、掩码字段、连接验证和配置迁移有单元/集成测试。

## 非目标

- 不实际实现 OpenVINO、DWPose、VACE 或任何模型推理。
- 不实现质量评分、候选选择或修复策略。
- 不宣称 ComfyUI 协议已经接入。

## 最终交付

最终答复必须列出协议类型、公共/内部接口、配置归属、迁移兼容、数据外发控制、测试结果、未验证项和关键文件绝对路径。
