# DeepSeek Harness：插件宿主、会话运行时与角色聊天适配

核验日期：2026-10-22。本文仅以指定的前期调查报告为项目背景，未阅读用户项目的其他文件。联网先用 GitHub 连接器读取官方分支与目录；递归树请求出现 Transport closed 后，在系统 TEMP 专用目录浅克隆官方仓库作静态阅读。没有安装依赖、启动 DSH、运行上游脚本或进行渠道实测。

实际读取版本：`deepseek-ai/deepseek-harness`，`master`，commit `687f282e8625c6b8d11ff58211a90524be2e4317`；该提交合并发布 `dsh@0.2.1-rc.2`。下文“源码事实”指该快照可直接核对的行为；“文档说明”是官方设计契约；“建议”是本报告推导，不构成已验证兼容性结论。[版本证据](https://github.com/deepseek-ai/deepseek-harness/commit/687f282e8625c6b8d11ff58211a90524be2e4317)。[在线开发文档](https://deepseek-harness.github.io/deepseek-harness/)本次能打开，但网页正文未被工具提取，因此细节引用固定版本的仓库文档与源码。

## 1. 核心判断

DSH 值得复用的是可组合 Agent 运行时：插件依赖、事件日志、工具策略、上下文压缩和任务恢复都有明确接口。它没有因此自动成为多人角色聊天产品。一个产品仍需自己定义“谁在和谁说话”、群聊参与规则、角色关系记忆、回复归属及消息送达语义。尤其要避免把 UI 的 Conversation、运行时 Session 和外部平台的群/私聊三个概念当成同一个对象。

源码将核心拆为 `session → system-prompt → llm → tools → agent-loop`；消费插件通过 `ctx.agents` 创建、恢复与投递，不应直接耦合具体循环。这个边界适合把“角色产品层”做成独立插件或网关，但现有宿主能力不能替代该层。[核心说明](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/subsystems/core.zh.md)、[Agent 工厂源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent-loop/src/index.ts)。

## 2. 源码地图与阅读入口

| 位置 | 本次核对内容 | 对聊天架构的意义 |
| --- | --- | --- |
| `vendor/cordis/src/fiber.ts`、`registry.ts` | effect、配置校验、依赖声明 | 人格/渠道插件能否正确启停 |
| `packages/core/agent/src/types.ts`、`agent-loop/src/agent.ts` | send、followup、steer、inject、cancel | 外部消息怎样进入模型轮次 |
| `packages/core/session/src/types.ts`、`surface.ts` | 格式 V4、事件与模型可见投影 | 审计真源与当前上下文分开 |
| `packages/core/tools/src/index.ts`、`agent-loop/src/tool-calls.ts` | restriction、guard、流水线、并发 | 角色行动的执行边界 |
| `packages/session/session-persistence-jsonl/src/lease.ts`、`storage.ts` | 写所有权、日志存储 | 重启、双开与备份 |
| `packages/session/session-checkpoint-policy/src/index.ts` | 模型/工具执行前 checkpoint | 避免先产生副作用再丢失调用记录 |
| `packages/compaction/compaction-basic/src/index.ts`、`region.ts` | 自动压缩、范围选择 | 长聊上下文预算 |
| `packages/schedule/schedule/src/runtime.ts`、`storage.ts` | 定向提醒、持久任务、回执 | 主动交流的调度参考 |
| `packages/boot/plugin-manager/src/operations.ts` | 安装兼容性预检 | 升级准入与回滚计划 |

以上路径均位于[固定版本源码树](https://github.com/deepseek-ai/deepseek-harness/tree/687f282e8625c6b8d11ff58211a90524be2e4317)；以下关键结论另给精确文件链接。

## 3. Cordis：依赖决定启动，effect 决定清理

官方教程明确：配置列表各项并发启动，YAML 前后顺序不是依赖顺序。插件导出 `apply(ctx)` 和可选 `name`、`Config`、`inject`；`inject` 声明硬依赖，缺服务时停在 PENDING。提供方被卸载或替换，依赖方也卸载，服务恢复后重新加载。可选服务应用 `ctx.get()` 探测，不能误以为“读取过服务”就获得后续依赖跟踪。[入门教程](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/cordis-tutorial/01-first-plugin.zh.md)、[服务教程](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/cordis-tutorial/03-services.zh.md)、[依赖实现](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/vendor/cordis/src/registry.ts)。

监听器、工具注册和子插件属于 effect；原生 WebSocket、文件 watcher、Node 定时器等需用 `ctx.effect()` 包装释放函数。fiber dispose 会等待异步清理。一个容易忽略的契约是：释放函数按逆注册顺序启动，但异步释放可以并发；必须先停收信再排空发送再关存储的流程，应放进一个 disposer 顺序 await。热重载只是生命周期重跑，不自动保存闭包中的 Map、任务去重或连接状态。[生命周期教程](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/cordis-tutorial/02-lifecycle-and-effects.zh.md)、[fiber 源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/vendor/cordis/src/fiber.ts)。

建议角色层把“订阅渠道、注册提示词、注册工具”交给 effect；把“用户关系、收件箱、发送回执”交给持久数据。不要把“卸载后不会继续运行”扩张成“运行中的任何第三方代码都能被强制终止”。

## 4. Session、Turn、Step 与 Conversation

Session 是仅追加事件日志，模型历史从日志派生。Turn 是一次驱动活动的边界；Step 是该轮中的一次模型调用及其要求的工具执行。一次长任务可能有许多 Step。UI Conversation 则把持久事件和客户端瞬态流组装成 Chat/Trajectory 等视图，它是呈现层，不是 QQ 群或租户隔离层。[Session 契约](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/session/src/types.ts)、[Conversation 说明](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/subsystems/conversation.zh.md)。

源码中三种投递别名很清楚：`followup = send(next-turn, true)`，排入下一普通轮并唤醒；`steer = send(next-step, true)`，运行中在后续 Step 边界领取；`inject = send(next-step, false)`，只加背景、不唤醒。后者可能赶不上已经领取批次的请求。`cancel` 默认清空待处理收件箱，再中止当前活动；`keepInbox` 可保留待办。`whenIdle()` 等整个 Agent 静止，不能用来确认某条特定消息已处理。[实际实现](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent-loop/src/agent.ts#L154-L243)。

建议外部渠道先生成带 `platform/account/conversation/sender/messageId` 的可信 envelope，再通过固定路由绑定 Session。每个群、私聊或角色实例是否共享上下文，应由产品显式决定。回复也应绑定原始 envelope，而不是让模型从文字提示里重新猜目标。格式 V4 已使用生产方拥有的来源词汇；插件来源可以保留可追踪性，但来源标记本身不授予或剥夺工具权限。[格式常量](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/session/src/types.ts#L90)、[投影源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/session/src/surface.ts)。

## 5. 压缩保证上下文继续，不保证关系记忆正确

Compaction 是可选 seam，分服务、provider 和命令消费者。basic provider 在 `agent/pre-step` 评估压力，也处理模型上下文溢出恢复。压缩写 `compaction/start/summary/end` 审计事件，并通过一条带 `surfaceOp: replace` 的用户消息替换模型可见区间；旧事件仍在日志里。范围按当前 surface 位置解释，不能简单把 start/end 当原始 seq 数值区间。锁覆盖摘要生成和替换，未完成压缩可在日志中识别。[压缩说明](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/subsystems/compaction.zh.md)、[basic 实现](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/compaction/compaction-basic/src/index.ts)、[范围实现](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/compaction/compaction-basic/src/region.ts)。

角色扮演适配建议分三层：稳定人设与边界由 system-prompt section 贡献；当前话题靠 Session 与压缩；跨天关系、承诺、用户纠正由带主体和来源的长期记忆保存。压缩摘要可能遗漏语气、否定和人物归属，不能直接当角色事实库。人设变更还应记录版本和人工纠正，避免重复把压缩结果写回人格形成自我强化。

## 6. 工具权限、并发与取消的实际边界

工具执行不是直接调用函数：注册表先做可见性/参数处理，再走 `tools/pre-execute`、单调 guard、around execute、post policy 和 result 通知。`tools.restrict()` 必须通过 Agent 作用域注册；guard 可以全局或按 Agent 拒绝，后来的 allow 不能覆盖已有 guard 的拒绝。嵌套调用只要经 `ctx.tools.execute` 并携带正确 Agent、parent token 和 signal，仍进入这条管线。[注册表与 guard](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/tools/src/index.ts#L1100-L1159)、[执行入口](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/tools/src/index.ts#L1364-L1598)。

这不等于所有插件已沙箱化。工具代码本身仍需合作转发 AbortSignal；同进程代码不能靠注册表硬杀。权限预设只是将 sandbox mode 与 approval policy 组合，真正限制由对应执行器和策略实施。`approval: never` 的准确含义是“不弹审批、所有 ask 自动拒绝”，不是“自动批准全部工具”；本来无需 ask 的操作如何处理仍取决于其他策略。[工具契约](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/tools/src/index.ts#L225-L280)、[审批实现](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/interaction/user-approval/src/index.ts)、[权限预设](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/subsystems/permission-presets.zh.md)。

源码中的工具调度以 exclusive 调用作屏障；仅明确声明 concurrency safe 的调用进入有界并发池，策略和结果仍按模型顺序提交。取消会停止补充新调用、排空已启动调用，并为跳过部分写错误结果。对角色产品，查询天气/检索记忆可以评估并行；修改关系、发送消息、切换角色应默认串行或具有幂等键。取消无法撤销已发送的 QQ 消息或已提交的外部写入。[调度源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent-loop/src/tool-calls.ts)。

## 7. 持久化、定时与崩溃恢复

持久 seam 返回 SessionHandle，只有 write handle 可修改；append 成功表示接受并保持顺序，flush 才是承诺崩溃后仍存在的屏障。JSONL provider 有跨进程单写者租约：Windows 用由路径派生的内核信号量，POSIX 用 flock；进程退出释放所有权，挂死但仍存活的写者不会被超时抢占。不要通过删除锁文件“修复”占用。[持久化契约](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/subsystems/persistence.zh.md)、[租约实现](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/session/session-persistence-jsonl/src/lease.ts)。

checkpoint policy 在模型派发和顶层工具 body 前 flush，失败时不继续产生对应副作用；嵌套调用复用外层 durable call。重启读取有效日志前缀，中断轮次由恢复路径补齐缺失工具错误和边界，记作 interrupted，而不是把整轮删除。它能说明“发生到哪里”，仍不能推断外部服务在超时前是否已完成操作。[checkpoint 实现](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/session/session-checkpoint-policy/src/index.ts)、[恢复工厂](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent-loop/src/index.ts)。

官方 schedule 是持久的宿主任务服务，绑定原 Session，到期可恢复冷会话；它依赖 Web Session controller 和持久后端，不能直接搬到任意 headless/最小 SDK 组合。重复任务补最近一次错过时点。同会话到期重复任务可合并投递；followup 后 flush，再写任务回执与下一目标。两次存储不是事务，flush 后崩溃可能重复提醒，回执只证明收件箱投递，不能证明模型执行或平台已送达。[schedule 说明](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/schedule/schedule/README.zh.md)、[投递源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/schedule/schedule/src/runtime.ts#L90-L142)。

## 8. 复用取舍与运维建议

建议复用生命周期、Session、工具管线、压缩和宿主 schedule；角色产品另建身份路由、发言决策、结构化关系记忆和 outbox。单人桌面陪伴可在一个 profile 里组合；多人或需要操作服务器的角色，应把闲聊权限与运维能力拆成不同 Agent/preset，必要时拆进程和凭证。共享一个宿主注册表并不自动满足租户隔离。

备份应同时覆盖 profile 组合配置、插件精确版本、Session 持久数据、schedule domain、长期记忆和渠道待发送状态；凭证单独保护。优先停收新消息、排空/flush 后做一致快照，再在隔离目录恢复验证。恢复不能只复制摘要，也不能把插件闭包状态当备份。观测应串联平台 messageId、SessionId、Turn/Step、tool callId、发送回执，并分别统计接收、入队、模型完成、发送四个阶段。[持久化边界](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/subsystems/persistence.zh.md)。OTel 服务不因挂载就自动上传；由调用方选择事件和脱敏，且内存队列不代替业务审计日志。[OTel 说明](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/telemetry/otel/README.zh.md)。

升级应固定“DSH＋preset＋插件＋数据格式”整套基线，先用副本验证再迁移。当前检查优先 `engines.dsh`，缺失时才回退 DSH peerDependencies；宽泛 peer 范围只能通过声明检查，不能证明行为兼容。V4 已是已发布 Session 格式，不能假设降级程序能读升级后写入的数据。[兼容规则](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/upgrade-guide/v0.2.1-alpha.3/plugin-engines-dsh/guide.zh.md)、[格式发布记录](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/session-format-status.zh.md)。whale、selfwake、meow-memory 等第三方组合尚未经本报告验证；发言调度和记忆写入应各有明确所有者，不能预设多套插件并行无冲突。

建议把运维恢复分成三种处理：连接失败由渠道重连并保留未处理消息；模型失败保留同一入站任务身份，允许重新生成；外部动作结果不确定则进入核对状态，先查询远端回执再决定重试。三者不能共用“整轮再跑一次”。例如用户让角色预约提醒后顺便发群通知，崩溃后应分别核查 schedule 是否已创建、群消息是否已发送，不应仅根据 Session 最后一条错误重复两项动作。宿主日志可以提供调用证据，真正的幂等键和业务补偿仍由动作所有者实现。

一个可实施的最小角色层应保留四份独立记录：身份映射记录绑定平台会话与 Session；入站记录保存原始消息 ID、授权结果和处理状态；记忆记录保存主体、来源与纠正；出站记录保存目标、内容版本和送达回执。模型可以提出动作，但不能修改这些记录中的可信身份字段。主人私聊能够授权更多工具，不应让“下一条群消息恰好进入同一 Session”继承该授权。对长期开放的群聊，这比继续增加人设提示更直接地决定可运营性。

依赖故障也应进入监控：fiber 停在 PENDING 可能意味着服务缺失而非插件已经成功启动；卸载 provider 可能连带重启消费者，影响渠道连接和内存状态。巡检应观察实际 fiber 状态、最后收信时间、最老待办年龄、持久化错误和最后成功回执。不要仅以进程存活、页面能打开或工具仍出现在清单里判断服务健康。[依赖状态与生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/cordis-tutorial/03-services.zh.md)。

## 9. 建议的场景验收与证据缺口

| 场景 | 应观察的通过条件 |
| --- | --- |
| A 群、B 群、私聊同时到达 | route 固定、记忆按主体授权、回复不会串目标 |
| 发言过程中第二条消息到达 | followup/steer 语义符合产品预期，每条有独立完成关联 |
| 长聊触发压缩 | 人设约束仍在；承诺/否定/人物归属可追溯，不凭摘要改写事实 |
| 工具审批被拒、取消发生 | 无新副作用派发；已执行与未执行明确区分；嵌套调用同受限制 |
| 发送成功后立即崩溃 | 重启不会盲目重发；不确定送达进入可核对状态 |
| 插件热重载、断网、冷会话提醒 | 连接不重复、资源退出完整、目标会话固定、提醒重复可识别 |
| 备份恢复与回滚 | 历史、任务、记忆、配置相互对应，原数据副本可恢复 |

以上是待实施验收，不是已通过测试。缺口包括：实际模型与长聊效果、Windows 上选定组合的沙箱覆盖、第三方插件对取消/并发的遵从程度，以及渠道端的发送幂等能力。DSH 的运行时契约已有较深工程积累；是否适合作为本项目最终底座，应由这些产品场景验证决定，不能以插件数量或 README 效果图替代。
