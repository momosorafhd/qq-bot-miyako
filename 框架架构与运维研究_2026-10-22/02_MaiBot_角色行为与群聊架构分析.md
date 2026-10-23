# MaiBot：角色行为与群聊架构分析

核验日期：2026-10-22。对象：[Mai-with-u/MaiBot](https://github.com/Mai-with-u/MaiBot)，实际读取 `main` 分支提交 [`c602a2780f4f4dda4a6be46d67abc1cfb1ad420c`](https://github.com/Mai-with-u/MaiBot/commit/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c)，`pyproject.toml` 声明版本 **1.3.14**；这不等于已核验同名发行包。

## 结论先行

MaiBot 最值得借鉴的是把“是否值得思考”“怎样行动”“怎样说话”“是否真正送达”拆为不同环节，并保留群聊中的等待、沉默与插话。它适合作为长期群友型角色的行为参考，但若目标是多角色、多用户、可分支的剧情聊天产品，仍需另建角色实例和剧情状态层。尤其不能把平台会话隔离直接当成角色世界隔离。

当前源码已采用 **Maisaka 对话循环、A-Memorix 记忆及 Host/Runner 插件运行时**。`heart_flow` 目录仍存在，但其管理器实际创建 `MaisakaHeartFlowChatting`；沿用早期“心流兴趣度”介绍，会错过当前主链。证据：[管理器](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/chat/heart_flow/heartflow_manager.py)、[版本](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/pyproject.toml)。

## 研究边界与证据等级

本报告在项目工作目录只读取指定前期调查报告。优先通过 GitHub `fetch`、`fetch_file` 读取官方 ref、源码树和核心文件；长文件返回容易截断，随后把官方仓库只读浅克隆至系统 TEMP 专用目录，用文本搜索与分段阅读补证。没有安装依赖、导入上游模块、执行上游脚本或接入真实聊天账号。

下文“源码核验”表示存在对应控制流，不代表在真实群聊中复现成功；“文档主张”只记录官方描述；“建议”是面向本项目的设计推论。官方站将自然对话、长期记忆、发言时机和控制台列为能力，但“越相处越懂你”等体验表达不能当作准确率或稳定性证据。[官方文档首页](https://docs.mai-mai.org/)

## 一条消息怎样变成角色发言

### 1. 消息入口、身份与持久化

源码核验：`src/main.py` 注册消息处理器；`chat/message_receive/bot.py` 把外部消息协调为 `SessionMessage`，执行接收 Hook、轻量处理、命令及后续聊天分发。`HeartFCMessageReceiver.process_message()` 获取或创建会话运行时，先把消息存数据库，再交给 `register_message()`，并通知记忆自动化服务。运行时创建失败时，入口仍可能存下消息，因此“消息在数据库里”不能证明 Planner 已执行。[启动入口](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/main.py)、[消息协调](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/chat/message_receive/bot.py)、[入库与注册](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/chat/heart_flow/heartflow_message_processor.py)。

会话 ID 由平台、可选账号与 scope、群号，或私聊用户号及 private 标记生成；群聊路径不把每位发言者变成独立会话。Platform IO 另外维护接收与发送路由表；其去重明确限于单条链路的技术重放，不做跨链路语义去重，停止时清除去重和出站跟踪内存。因此双适配器同时接同一群、重启后上游重放，都应成为验收场景。[会话键](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/common/utils/utils_session.py)、[IO 管理器](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/platform_io/manager.py)。

### 2. 决策不是每条消息都调用一次大模型

源码核验：`MessageTurnScheduler` 依次考虑消息防抖、快速反应模式的 wait 续接、静默消费、@ 强制触发、空闲退避与动态门控。注意静默模式的“trigger”是调度消费消息，不应误读为强制对外发言；通过门控也只是进入 Planner，Planner 仍能等待或停止。[调度器](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/turn_trigger/scheduler.py)。

动态门控先用消息是否提名、是否 @ 他人、问号、媒体占位、近期自身发言比例、消息密度和间隔等特征估计 reply 概率；再根据滑动窗口的预计回复数、实际 reply 次数和配置频率调整阈值。源码中的系数及离线阈值来自项目自身样本说明，不能解释成普遍适用的社交规律，也不是本次测得的效果。[概率估计](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/turn_trigger/reply_likelihood.py)、[动态门控](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/turn_trigger/dynamic_gate.py)。

建议借鉴“两层决策”：廉价门控减少无意义规划，角色规划器处理语义与礼貌。不要直接复制拟合权重；先采集本项目的“该回应却沉默、无须回应却插话”样本，再校准阈值。单人角色扮演通常更强调即时回应，群聊频率策略不能直接当默认私聊策略。

### 3. 会话循环与并发边界

源码核验：每个会话运行时有消息摄入锁、内部循环任务、消息缓存和 RUNNING/WAIT/STOP 状态；新消息可进入缓存并影响待处理轮次。管理器另有创建锁，避免同会话重复建循环，并对活跃运行时做容量淘汰。它管理的是单进程内对象，不是分布式会话锁。[运行时](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/runtime.py)、[会话管理器](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/chat/heart_flow/heartflow_manager.py)。

推理引擎组织“模型—工具—模型”逻辑轮次；工具执行结果写回上下文。上下文选择还会补齐工具轮次和其用户锚点，必要时超过普通消息窗口，以免把 tool call 与结果割裂。这值得借鉴，但意味着消息条数上限不等于硬 token 预算，应同时观察实际输入、工具定义和视觉内容的成本。[推理引擎](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/reasoning_engine.py)、[上下文选择](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/chat_loop_service.py)。

### 4. 规划与角色表达分离

源码核验：Planner 可以调用 `reply`、`wait`、`stop` 及查询记忆等工具。`reply` 接受目标消息和 `reply_reference`，再调用 replyer 生成可见文字，可叠加表达方式选择、分句、错字等后处理；重复回复同一消息时存在避免重复的提醒。replyer 的身份来自全局 personality 与 bot 名称，并可随机选择多种表达风格。[reply 工具](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/builtin_tool/reply.py)、[人设与生成](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/chat/replyer/maisaka_generator_base.py)。

建议保留“行为意图—角色台词”的接口，但让两者共享结构化场景与事实引用，避免 Planner 猜出的关系或事件被 replyer 当成既定事实。错字、表情和分句只改善表层节奏；它们不能代替角色动机、知识边界、世界设定和连续性约束。剧情长回复还应允许关闭会破坏段落的闲聊后处理。

## 记忆：已有证据治理，仍缺剧情语义

源码核验：A-Memorix 在宿主启动中被初始化，默认数据位于实例的 `data/a-memorix`，包含 SQLite 元数据、Faiss 向量与图相关持久化结构；不是只备份 `MaiBot.db` 就能保全的单库系统。[记忆路径](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/A_memorix/paths.py)、[向量存储](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/A_memorix/core/storage/vector_store.py)、[图存储](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/A_memorix/core/storage/graph_store.py)。

启发式召回按会话缓存、最小间隔和新增消息数控制，再由当前聊天印象检索。结果有来源过滤：episode 限定对应聊天摘要；人物事实需属于当前活跃人物；跨聊天记忆受配置及群转私、私转群选项约束；未知来源默认不放行。这是“先检索、再按来源决定能否注入”的可借鉴机制，但当前人物身份键仍主要来自平台与用户，不天然包含角色实例或剧情分支。[召回与过滤](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/memory/heuristic_injector.py)。

人物事实写回有有界后台队列，满时警告并跳过；历史事实重分类游标可持久化续跑。直接事实核验要求同一会话、同一人物的原始自述与可定位引文，并排除若干暂时性、疑问和第三方表达。事实账本区分 authority、stability、active/conflicted/superseded/retracted 及证据、转移记录，不能说它“没有事实区分”。但这些是现实人物资料治理，尚不能自动区分“玩家本人是医生”“角色在本分支是假扮医生”“作者设定此人为医生”。[写回服务](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/services/memory_flow_service.py)、[直接事实核验](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/services/person_fact_verifier.py)、[事实状态机](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/A_memorix/core/storage/metadata_fact.py)。

建议为记忆增加 `world_id / character_instance_id / player_id / branch_id / source_message_revision`，把作者 canon、角色所知、角色误信和现实用户资料分层。删除或改写一条剧情消息时，必须能定位派生摘要、事实和向量并撤销；仅清空当前上下文不会完成这项工作。当前 `/clear` 源码明确处理 Maisaka 历史上下文及恢复标记，不能把它宣传成全部长期记忆删除。[清空上下文命令](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/chat/message_receive/bot.py)。

## 插件、发送回路与失败语义

源码核验：插件运行时采用 Host/Runner、RPC、命名 Hook、能力接口与超时、熔断相关模块；Supervisor 负责 Runner 启动、健康检查及有上限的重启。进程边界有利于故障定位，但不等于插件受到操作系统安全沙箱限制，也不等于每个插件独享一个进程。Hook 可改写提示词、工具定义和回复，角色一致性不能只审查主提示词。[Supervisor](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/plugin_runtime/host/supervisor.py)、[Hook 分发](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/plugin_runtime/host/hook_dispatcher.py)、[规划 Hook](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/chat_loop_service.py)。

发送经过 send service 构建消息、Hook、Platform IO 路由和投递回执；至少一条路由成功即 `has_success`，成功后才执行对应存储与记忆通知。多个路由存在部分成功语义，不能把总成功当作所有渠道都成功。它也没有由本次源码阅读证明跨进程崩溃的 exactly-once 投递。[发送事务边界](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/services/send_service.py)。

建议把“生成成功、投递成功、平台确认、已入历史”分开记录；消息 ID 与逻辑轮次 ID 同时贯穿日志。生成完成后适配器断线，应保留可查看的待发状态或明确失败，不能再次重做有副作用的工具。`wait` 和子任务属于运行时状态，重启后从近期数据库消息恢复，并不证明所有中断工具会精确续跑。[恢复与停止](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/runtime.py)。

## 运维清单与验收

主库默认 `data/MaiBot.db`，启用 SQLite WAL，启动有版本迁移；代码更新也有回退路径，但代码回退不代表数据迁移可逆。运维应以“一组相互匹配的程序、配置和数据快照”为恢复单位。[数据库](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/common/database/database.py)、[迁移入口](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/common/database/migrations/bootstrap.py)、[自更新](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/common/self_update.py)。

| 时机 | 可操作动作 | 验收点 |
| --- | --- | --- |
| 初次接入 | 固定核心 commit、适配器和插件版本，画出账号/scope/群的路由表 | 两个机器人账号接同群时不串消息；同一路径重放被正确处理 |
| 每次升级前 | 停止接收并等待可结束工作，备份完整实例配置、data、插件及媒体；一致性复制 WAL 数据 | 在独立实例恢复，主库、元数据、向量与图均可读 |
| 升级时 | 先用副本运行迁移，再切换；保存旧环境与升级前数据 | 失败时可整体退回；禁止旧代码直接打开已变更的数据副本 |
| 日常巡检 | 看接入连接、门控原因、Planner/replyer 耗时、输入量、投递失败、Runner 重启和记忆队列丢弃 | 能回答一次未回复是过滤、等待、模型失败还是发送失败 |
| 退出重启 | 验证优雅停止、进程异常退出、上游重放三条路径 | 不把已发送内容再发；清空后的上下文不被恢复；中断工具状态可解释 |

项目已有启动分阶段诊断、事件循环 watchdog、生成诊断、Maisaka 监控事件与 token 分段统计，可用于定位接入、规划、工具、生成和发送耗时；是否导出为外部监控及告警需部署时补齐。保存完整提示词和推理预览会扩大聊天资料的落盘范围，建议设置保留期与访问范围。[启动诊断](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/common/startup_diagnostics.py)、[监控事件](https://github.com/Mai-with-u/MaiBot/blob/c602a2780f4f4dda4a6be46d67abc1cfb1ad420c/src/maisaka/monitor/events.py)。

角色场景还应验收：同一玩家同时扮演两个角色不共享秘密；同一角色的平行剧情不相互召回；改写死亡事件后旧摘要失效；重生只替换选定候选且不重复执行工具；NPC 的误信不会晋升为作者 canon；群聊连续多人发言时引用目标正确；模型超时后角色收到简洁一致的失败表达。这些是建议验收项，本次均未运行。

## 原型应怎样判断是否值得采用

建议把首轮原型拆为“群友参与”和“剧情扮演”两组样本，分别评价。前者关注插话是否合适、回应对象是否正确、等待是否自然、重复发言与打扰是否可控；后者关注角色知识边界、关系连续性、改写后记忆是否纠正、多个分支是否独立。两组样本的失败原因不同，合并成一个满意度分数会掩盖问题。

对每次运行保留输入事件、门控理由、进入 Planner 的时刻、所用记忆来源、reply 目标、可见输出与投递结果，并记录模型和提示词版本。先人工标注少量有代表性的聊天，再观察调整配置前后的变化；本报告不预设合格率。门控调得更保守而回复变少，不能直接称为质量提升；增加主动消息也不能直接称为更像长期角色。

故障验收宜选可控注入：让记忆服务暂时不可用、令一个工具超时、断开一条出站路由、在 wait 期间重启，再比较数据库、运行时和平台可见消息。源码已有部分异常降级与恢复路径，实际是否保持一致仍需逐项检查。对本项目而言，最关键的退出条件是：能够解释一次异常，并能恢复到用户认可的剧情状态；仅能重新启动进程还不够。

## 源码阅读地图与采用判断

推荐阅读顺序：`main.py` → `platform_io/manager.py` → `message_receive/bot.py` → `heartflow_message_processor.py` → `heartflow_manager.py` → `maisaka/runtime.py` → `turn_trigger/scheduler.py` → `reasoning_engine.py` → `chat_loop_service.py` → `builtin_tool/reply.py` → `maisaka_generator_base.py` → `send_service.py`；记忆另追 `memory_flow_service.py`、`heuristic_injector.py` 与 `A_memorix/core/storage`。上文链接均固定到本次提交。

优先借鉴：门控与语义规划分工、等待作为一等行为、目标消息引用、工具轮次完整性、事实证据与状态转移、投递回执分层。谨慎采用：离线群聊概率权重、全局人格、隐式跨会话人物资料、自动风格学习、只改代码的回滚。对于角色扮演产品，更合理的定位是行为机制参考或可控群聊内核；完整剧情编辑器、版本化世界状态与记忆撤销链需额外建设。

仍缺证据：真实群聊回复节奏与成本、长时间运行及队列积压、实际平台回执可靠性、断电时多存储一致性、插件组合故障影响、全量记忆删除与分支回滚行为。仓库中存在诊断和恢复代码，只能说明设计覆盖这些问题，不能据此认定已完成生产验收或维护成熟度认证。
