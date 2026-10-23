# Hindsight：长期记忆服务、角色经历与运维分析

研究日期：2026-10-22。读取官方 `vectorize-io/hindsight` 的 `main`，固定提交 `517192d3bfef0bd7b3efcdedc7829445a55c3ae9`。该提交 API 包版本 **1.1.0**，coding-agents 集成版本 **0.8.2**；版本号分别属于不同组件，不能混用。[API 版本](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/pyproject.toml#L1-L10)、[集成版本](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-integrations/coding-agents/package.json#L1-L10)

提交时间为 2026-10-22 09:37:54 UTC。本轮为联网静态研究，未安装或运行上游服务，未验证聊天质量、费用、吞吐或灾备效果。先用 GitHub 连接器读取官方分支、目录和源码；`memory_engine.py` 约 1.23MB，连接器全文和指定行读取均返回空内容，因此按授权浅克隆到系统 TEMP 专用目录补读，没有把源码或依赖写进用户项目，也未执行安装脚本。项目背景只读取指定前期报告。

## 1. 判断：适合记忆基础设施，不能替代角色与剧情管理

Hindsight 值得借鉴的是“原始材料—抽取记忆—证据化归纳—按需检索与推理”的完整组织，以及独立服务、异步摄取、可查看来源和删除维护的工程边界。它可以承接角色经历，但不会自动判断一句话属于现实、剧中设定、角色谎言、助手提案还是被用户重生掉的旧回复。对日常角色扮演，优先把它作为可替换记忆后端，让前端角色运行时负责身份、授权、剧情版本和写入资格。

关键区分是：`retain` 写入与抽取，`recall` 检索，`reflect` 只读生成基于证据的回答。Reflect 不是“把反思自动变成新的客观事实”；其结果若被创建成 mental model 或被应用再次 retain，才进入另一条保存路径。[接口实现](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L15778-L15820)、[反思说明](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/reflect.mdx#L20-L56)

## 2. 源码阅读地图

| 路径 | 研究用途 |
| --- | --- |
| `hindsight-api-slim/hindsight_api/api/http.py` | HTTP 参数、异步请求、断线取消和维护入口 |
| `engine/memory_engine.py` | retain/recall/reflect 编排、文档删除、重处理、任务取消和幂等 |
| `engine/retain/orchestrator.py`、`fact_extraction.py`、`fact_storage.py` | 分块抽取、embedding、实体和链接、写事务及提交检查点 |
| `engine/memories/pg/recall.py`、`engine/search/*` | PostgreSQL 召回分支、关键词/向量与时间检索 |
| `engine/reflect/agent.py`、`tools.py` | 只读工具循环、证据来源、错误和预算 |
| `engine/task_backend.py`、`worker/poller.py` | 数据库任务队列、并发领取、背压、重试和失败终态 |
| `extensions/builtin/tenant.py`、`tenant.py`、`operation_validator.py` | 默认认证、租户 schema、bank 与读写标签范围扩展 |
| `admin/cli.py`、`migrations.py` | 数据库备份恢复、索引修复、迁移和 worker 管理 |
| `hindsight-integrations/coding-agents/src/dsh.ts`、`core/transcript-dsh.ts`、`core/chat.ts`、`core/bank.ts` | DSH 生命周期、来源过滤、增量保存、游标、项目 bank 解析 |

以下所有源码链接固定在[该提交](https://github.com/vectorize-io/hindsight/tree/517192d3bfef0bd7b3efcdedc7829445a55c3ae9)。文档用来解释设计，遇到与实现冲突时不据文档推导额外能力。

## 3. Retain：从材料抽取记忆，而非逐字聊天档案

**源码事实：** 输入可包含正文、上下文、时间、document ID、标签、metadata 和抽取策略。流水线调用模型抽取事实，对抽取文本生成 embedding，再解析实体和检索相关语义链接；读取较重的操作尽量放在写事务外，检索必要的事实及链接在事务内提交，部分图维护放到后续阶段。代码记录 `facts_committed` 等检查点，说明“任务仍未完成”与“完全没写入”不是同义词。[抽取与向量](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py#L1351-L1407)、[事务分工](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py#L672-L902)、[提交检查点](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py#L100-L137)

**文档主张：** 原始记忆分 `world` 与 `experience`，核心是归属视角：用户说“我买了车”应是关于用户的 world，属于 bank 的 Agent 自己做过的事才是 experience。上下文应明确谁在说话。模型抽取的是带理由、情感、时间和关联的叙述，不只是孤立短句。[分类与作者归属](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/retain.md#L57-L83)

这里的“事实”仍是从输入抽取的主张，不是外部真实性认证。角色声称“我是王国最后的法师”，在剧情内可以成立，在用户现实档案中则不成立。需要在写入前保留 `speaker_id`、角色实例、叙事层、现实模式及原始消息位置，并为用户明确纠正保留高优先级来源，不能期望一个 `world` 标签完成真假分离。

Hindsight 在本次读取的核心路径中以 document、chunk、memory unit、实体和关系组织材料；本文不把 experience 擅自等同于独立 Episode 对象。角色的“一次共同旅行”可以用稳定文档及事件标识组织，抽取记忆保留起止时间和来源，但剧情阶段、章节边界和分支归属仍应由应用定义。事件发生时间与系统获知时间也必须分别保存：补录上周经历不能因为今天摄取就变成“今天发生”。[时间设计](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/retain.md#L138-L155)

Retain 后的后台 consolidation 将多条记忆归纳成 observations，并跟踪支持记忆、引文、proof count 和历史。它适合总结反复出现的偏好、关系变化和经验；这些是证据化归纳，仍可能误读、过度概括或把重复转述当成多个证据。Proof count 不是独立证人数量，更不是事实概率。[归纳机制](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/observations.mdx#L13-L49)

## 4. Recall 与 Reflect：取证和回答分层

**源码事实：** recall 对各记忆类型执行语义、关键词、图和时间召回，合并后进行排序、多样性处理和 token 截断；PostgreSQL 实现把部分语义/BM25 查询合并为 SQL，不能把文档“四种策略”机械理解为四个独立数据库产品。请求支持类型、时间、标签、标签组、来源片段及来源事实选项。[主召回入口](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L9293-L9369)、[PG 查询](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memories/pg/recall.py#L1-L118)

默认可以检索 world、experience 与 observation；`prefer_observations` 可按来源关系消除原始事实和归纳的重复。角色聊天宜保留最新细节的原始事实，同时用 observation 做压缩线索，避免将尚未完成 consolidation 的近期情节漏掉。问“昨天我答应了什么”时，使用明确时间锚点与原话来源，比只取情绪或人物画像更可靠。[召回 API 与来源](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/api/recall.mdx#L52-L165)

Reflect 启动只读 Agent 工具循环，优先看可复用 mental models，再看 observations，必要时检索原始记忆和上下文。Mental model 是显式保存、可刷新的综合答案；它与原始事实不同。Disposition、reflect mission 和 directives 能影响推理口吻与规则，但 retain mission、observations mission 分别影响写入抽取和归纳，不能只改一个“人格字段”就认为全部记忆行为随之改变。[反思层次](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/reflect.mdx#L20-L56)、[任务作用域](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/api/memory-banks.mdx#L278-L334)

**分析建议：** 闲聊默认 recall，再由角色主模型生成回复；对“我们关系如何变化”“哪些约定冲突”这类跨事件问题按需 reflect。不要每条寒暄都运行完整反思，也不要把反思文本未经确认地回写为新经历。对没有原话支撑的“角色心理推断”加单独推测标识，禁止反过来覆盖用户明确纠正。

## 5. Bank、身份与授权：命名隔离不等于访问控制

Bank 是记忆与配置的组织单元。内置默认 `DefaultTenantExtension` 没有认证；`ApiKeyTenantExtension` 校验一个配置的 key，并返回配置的同一 schema，它不是自动生成多个用户权限域的系统。租户扩展可据凭据返回不同 schema。部署时必须同时处理网络入口、身份认证、bank 授权和后台任务的租户上下文。[默认及内置认证](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py#L8-L90)、[租户接口](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/extensions/tenant.py#L54-L109)

也不能反向说它完全没有细粒度权限能力：当前 `OperationValidatorExtension` 可给调用者解析强制读取与写入标签范围；引擎将读取范围与用户查询做 AND，按 ID 写入也检查可见/可写性，并拒绝受限调用者进行整 bank 导出、删除、配置和部分整库观测操作。关键是显式配置服务端策略，而非相信客户端每次都会传对 tags。[服务端范围契约](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/extensions/operation_validator.py#L963-L1035)、[按 ID 写入检查](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L3623-L3690)、[整 bank 拒绝](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L3854-L3868)

**分析建议：** 私密用户档案、角色实例的共同经历、公共世界设定分别设定访问策略；角色、用户、世界和剧情分支使用稳定 ID。允许共享的 canon 设为只读来源，用户可写经历限定在所属范围。选择多个 bank 还是同 bank 标签，应依据是否允许跨域 consolidation 与统一删除决定。特别小心 `observation_scopes: shared`：它方便跨会话归纳，也可能把原本应隔离的故事融合成全局信念。[观察范围](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/observations.mdx#L49-L66)

## 6. 异步摄取、幂等、删除与重建

后台任务以 PostgreSQL `async_operations` 为持久 broker，API 可内置 worker，也可单独部署。Poller 使用并发安全领取机制、任务阶段与时限、背压延迟、失败重试和终态更新；API 返回 operation ID 只代表提交状态，必须继续跟踪最终结果。父子批量任务还要检查子任务失败原因，不能把 HTTP 成功当作记忆已可召回。[任务后端](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/task_backend.py#L153-L255)、[领取与终态](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/worker/poller.py#L591-L797)、[服务部署](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/services.md)

服务支持调用者 operation ID 的重放识别；并发首次提交由数据库唯一约束兜底。稳定 `document_id` 负责同一来源材料的更新身份，与 operation ID 的“同一提交”不是一回事。异步批量请求拒绝重复 document IDs，避免平行子任务对同一文档追加丢更新。角色端建议使用“会话/章节＋已接受版本”生成 document ID，使用内容和模式生成幂等操作 ID，不要每次重试随机换 ID。[提交幂等与并发限制](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L23320-L23368)

取消是协作式：先把任务状态改成 cancelled，执行者在检查点停止，已经提交的内容不会因取消自动回滚。删除 document 会处理关联记忆与链接、失效依赖 observations，并安排图维护；整 bank 删除是另一条范围更大的路径。`reprocess_document` 从保留的原文和参数重新 retain，使用 replace 模式；它是重新抽取，不是恢复历史同一组模型输出。[取消语义](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L22217-L22302)、[文档删除](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L11321-L11400)、[重新抽取](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L14093-L14157)

**分析建议：** 聊天删改先写应用侧撤销记录，停止该来源的待处理摄取，再删除或替换文档，核查 observation、mental model 和当前上下文。聊天数据库与记忆服务之间使用持久 outbox 和来源版本号，避免旧异步请求在新版本删除后又写回。分支重生优先切换命名空间或有效版本，再做后台清理；不要在确认生效前向用户承诺“已经彻底忘记”。备份中的历史数据也有独立保留策略。

## 7. DSH coding-agent 集成：可参考适配，不能直接充当陪伴插件

**源码事实：** DSH 接入按 session header 的 cwd 解析工作区；默认 bank 模板为 `coding-agent::{gitProject}`，同仓库 worktree、不同 coding agent 共享项目记忆。这里的项目名、`{user}` 或 `{channel}` 模板变量只是命名输入，不能替代认证。两个用户共用服务或同名项目时需要应用显式提供稳定域和授权。[项目 bank 规则](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-integrations/coding-agents/src/core/bank.ts#L1-L55)

DSH `preStep` 只对真正用户来源的新输入召回，跳过工具续步，并避免重复注入相同块；turn stopping 后重新读取包含最后回复的日志，触发 write-back。转录标准化只收真正用户消息、助手正文及压缩工具调用，跳过 tool result 与其他插件上下文，避免把召回材料再当用户原话灌回记忆。原始工具输出被省略，意味着它适合保留工作叙述，不能据此证明某项外部行动确实成功。[生命周期](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-integrations/coding-agents/src/dsh.ts#L246-L303)、[来源过滤](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-integrations/coding-agents/src/core/transcript-dsh.ts#L1-L110)

这里的“真正用户来源”按宿主 source.kind 等事件字段识别，不能视为对人类来源的独立认证；例如 selfwake 会将自己的消息标成 user，组合时需要额外过滤与验收。

保存使用稳定 `conversation:<sessionId>` 文档，按游标判断 replace、append 或 skip，构造确定性 operation ID，并保留未确认追加的数据；运行时 write-back 是非阻塞链，失败写诊断，不应推断为任意关机都绝不丢失。宿主结束时机、游标持久化、服务接受状态仍需验收。[保存身份与缓冲](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-integrations/coding-agents/src/core/chat.ts#L317-L455)、[非阻塞及 flush](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-integrations/coding-agents/src/core/runtime.ts#L320-L390)

历史 issue **#4818** 报告 0.6.1 集成仍写 `source.kind="plugin"`，被 DSH session format v4 拒绝；官方维护者明确表示在 **0.8.0** 修复。本次固定源码已使用 `plugin:hindsight`，还兼容 `snapshotEvents()` 与旧 `events` 访问，不能把历史缺陷写成当前未修复问题。它提醒我们宿主事件格式和来源契约是兼容性测试重点。[问题与官方关闭说明](https://github.com/vectorize-io/hindsight/issues/4818#issuecomment-5889807393)、[当前注入来源](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-integrations/coding-agents/src/dsh.ts#L223-L237)、[事件访问兼容](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-integrations/coding-agents/src/dsh.ts#L133-L141)

## 8. 成本结构、备份恢复与场景验收

成本分为：retain 的分块抽取、事实 embedding 与实体解析；consolidation 的归纳、去重与后续刷新；recall 的查询 embedding、数据库多路检索和 reranker；reflect 的多轮模型调用、内部检索和输出处理。历史回填、全文 replace、失败重试、改模型重建都会产生额外工作。不能只按“每条聊天一次 embedding”估算，也没有依据给出统一硬件配置或月费。[抽取实现](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py#L1351-L1407)、[反思循环](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/engine/reflect/agent.py)

文档将标准部署描述为 API、worker、Control Plane，状态主要依赖 PostgreSQL。但当前代码还有自定义 memories store、对象文件存储等扩展，不能将“API 无状态”扩大成任何部署只备份数据库就足够。标准 PG 的 admin backup 使用 REPEATABLE READ 与 binary COPY 生成表快照；restore 先校验列，再事务性清空并恢复目标 schema。外置对象存储、自定义 store、服务配置和凭据仍须独立覆盖；恢复到旧程序也不保证 schema 兼容。[备份实现](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/admin/cli.py#L336-L474)、[配置中的文件存储](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-api-slim/hindsight_api/config.py#L3682-L3699)

| 运维清单 | 应达到的状态 |
| --- | --- |
| 固定版本与依赖 | API、集成、迁移、embedding 维度/模型、reranker、抽取/反思模型和 bank 配置可追溯 |
| 认证与隔离 | 默认无认证路径不直接暴露；tenant 与 operation validator 明确配置；跨用户、标签、日志和维护 API 都测越权 |
| 队列运维 | 监控 pending 最老年龄、processing 卡住、failed、重试与背压；停 worker 前释放任务，重启后核对重复提交 |
| 备份与迁移 | 保留 PG 与对象存储一致性信息、应用源事件及游标；隔离环境恢复；迁移后检查索引与来源引用 |
| 可观测性 | 用 `/health/live`、`/health/ready` 区分存活和依赖就绪；观察 operation 终态及按 scope/provider 的模型 token 与耗时 |

官方 admin 工具包含 worker 管理、迁移、`repair-bank` 索引与孤儿 observation 修复；监控支持 Prometheus 和 OpenTelemetry。它们提供排障手段，不代表部署已经具备高可用或恢复承诺。[管理工具](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/admin-cli.md)、[监控](https://github.com/vectorize-io/hindsight/blob/517192d3bfef0bd7b3efcdedc7829445a55c3ae9/hindsight-docs/docs/developer/monitoring.md)

| 验收场景（本轮未执行） | 通过条件 |
| --- | --- |
| 两角色、两用户同名且共享世界 | 公共 canon 可读，私密经历不串；用户不能用省略标签或改 bank ID 绕过服务端范围 |
| 现实偏好与剧中对白相矛盾 | 回复明确使用当前叙事层，虚构台词不覆盖现实用户档案 |
| 更正、删除、重生和分支切换 | 原始来源、归纳、mental model、旧队列与上下文一起处理，旧剧情不复活 |
| 队列执行一半断电、请求超时后重试 | operation 和 document 身份保持，能解释部分提交，无重复追加或静默丢失 |
| DSH 续步、上下文压缩、最后一轮后退出 | 不重复注入，不回灌插件提示；最后的已接受回复可追踪到摄取终态 |
| 新主机恢复和模型升级 | 来源与附件可读，索引正确，原模型向量与新模型策略明确，恢复结果可用代表性问题核验 |

适用结论：Hindsight 比轻量笔记插件提供更完整的记忆服务与运维接口，适合对跨会话证据检索和可维护性有要求的方案。主要代价是服务、队列、模型调用与权限配置的复杂度。角色扮演仍须补齐 canon 与叙事层、用户/角色/剧情隔离、接受版本、来源可信度和可纠正体验；这些缺口不能由 reflect 的人格口吻自动补足。
