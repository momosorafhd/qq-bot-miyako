# NekroAgent：行动沙箱、工作区记忆与运维分析

研究日期：2026-10-22。对象为官方 `KroMiose/nekro-agent` 的 `main`，实际读取提交 `ea7b90eb83bd80061b2a177510c27c957f7f980d`；该提交 `pyproject.toml` 标记版本 **2.4.0**。本文是静态源码研究，未启动机器人、沙箱或数据库，未做攻击、负载与恢复实测。只读取指定前期报告作为项目背景，没有读取用户项目其他文件。[版本锚点](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/pyproject.toml#L1-L6)

提交时间为 2026-10-09 07:43:41 UTC。文中“源码事实”指读取实现；“文档主张”只说明上游宣称；“分析建议”是面向角色扮演的取舍。没有运行证据的行为不视为已经验收。

## 1. 判断：值得借鉴行动执行层，但要重新审视信任边界

NekroAgent 的价值是把多人聊天、人格提示、生成代码、宿主插件与持续工作区放在同一条控制链。它不是仅靠提示词模拟“做了事情”：模型能生成 Python，通过容器执行计算、处理文件，再回调宿主插件发送消息或发起较长任务。当前版本还包含工作区级记忆、Episode、知识库及 Claude Code 委托，因此早期“代码生成＋容器沙箱”的概括已经不完整。[运行主链](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/agent/run_agent.py#L45-L150)、[工作区模型目录](https://github.com/KroMiose/nekro-agent/tree/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/workspace)、[记忆目录](https://github.com/KroMiose/nekro-agent/tree/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/memory)

对日常角色扮演，建议优先复用渠道适配、触发合并、行动状态与来源追踪。不要因为生成代码运行在 Docker 内，就认为宿主工具也被同样隔离。该版本 RPC 的认证、反序列化与权限选择形成一个需要优先处理的边界，后文给出具体证据；这不是漏洞利用复现。

## 2. 源码阅读地图

| 阅读位置 | 回答的问题 |
| --- | --- |
| `services/message_service.py` | 入站校验、消息持久化、触发、配额、防抖、频道任务与取消 |
| `services/agent/run_agent.py`、`templates/history.py` | 人设和插件提示、历史和记忆注入、模型重试、生成代码迭代 |
| `services/sandbox/runner.py`、`ext_caller*.py` | 容器限制、共享目录、RPC 代理、超时及执行日志 |
| `routers/rpc.py`、`services/rpc_service.py`、`plugin/collector.py` | 令牌校验、反序列化、宿主方法分发与工具发现 |
| `plugins/builtin/basic.py`、`services/chat/universal_chat_service.py` | 消息工具、去重、适配器发送与回复返回路径 |
| `services/workspace/container.py`、`client.py`、`plugins/builtin/cc_workspace/main.py` | 持久工作区、后台委托、取消、结果投递及重启补取 |
| `models/db_mem_*`、`services/memory/*` | 段落、实体、关系、Episode、衰减、沉淀与重建 |
| `docker/docker-compose.yml`、`core/db_migration.py`、`__init__.py` | 持久卷、Docker 权限、启动迁移、恢复及关机清理 |

以上路径均相对官方仓库，链接使用同一提交；可从[固定源码树](https://github.com/KroMiose/nekro-agent/tree/ea7b90eb83bd80061b2a177510c27c957f7f980d)复核。

## 3. 从消息到回复：模型生成的是行动程序

**源码事实：** 人类消息先做格式与禁止内容检查，创建包含频道与触发用户的 `AgentCtx`，交给插件消息钩子；`BLOCK_ALL` 可在持久化前截断。其余消息落库后，按显式触发、叫到人设名称、@、随机或内容条件判断是否启动。用户禁用、频道停用、旁观模式和配额会继续约束触发。旁观模式下“记录消息”和“生成回复”是两件事，不能把没有回复误诊为渠道丢消息。[入站和触发](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/message_service.py#L300-L463)

调度器以 `chat_key` 保存防抖时间、最新待处理消息和正在运行的任务。同频道运行时的新触发合并在待处理槽，结束后再启动后续一轮；这不是每条触发消息都拥有独立队列项。由于完整消息另行落库，“待处理只留最新触发”也不等于历史只剩最后一条。该状态是进程内字典，不能据此声称多个服务副本能自动保持同频道串行。[频道调度](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/message_service.py#L63-L170)、[结束后续跑](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/message_service.py#L245-L298)

`run_agent` 获取频道有效配置和人设，将平台信息、人设正文、插件声明、激活规则、调用优先级、示例与历史编译成请求。模型结果经过解析后交给 `limited_run_code`，普通完成即结束；工具要求模型继续、执行错误、超时等会把输出和新到历史加入下一轮。代码失败可能发生在外部动作已经完成之后，因此“再生成一段代码”不能提供业务层面的恰好一次执行。[上下文构建](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/agent/run_agent.py#L45-L150)、[停止类型与迭代](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/agent/run_agent.py#L182-L356)

回复通过沙箱代理调用宿主的消息工具，再经统一聊天服务到具体适配器。`send_msg_text` 有空文本、适配器与近期重复消息检查，但缓存去重不等于持久幂等：重启、不同表述或“已发成功但确认丢失”仍需应用补偿。[发送工具](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/plugins/builtin/basic.py#L247-L340)

**分析建议：** 闲聊优先走直接回复；需要计算、文件或外部行动时才开放代码路径。为有副作用的工具增加 `action_id`、目标绑定、执行收据与重复提交检测，且由确定性程序校验。角色说“我已替你预约”必须有成功收据；失败信息由角色表达层转述，避免把堆栈直接当作角色对白。

## 4. 两类沙箱必须分别评估

**源码事实：一次性行动沙箱。** `runner.py` 生成按频道划分的共享目录，写入代码与 API 代理，挂载上传目录为只读，同时把依赖目录、pip 缓存和本轮共享目录以读写方式挂入。容器用户为 `nobody`，配置了内存与 CPU 上限、执行超时及全局并发信号量；网络使用 bridge，并可访问 `host.docker.internal`。这里的资源值是实现中的限制，不是本报告测出的硬件需求或吞吐。宿主非 Docker 路径还显式设置 `apparmor=unconfined`，不能笼统称为最小权限沙箱。[创建容器](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/sandbox/runner.py#L144-L256)

跨频道共享的可写依赖与缓存意味着并非所有挂载都是频道私有。动态导入器能安装依赖，网络也没有在此处限制到业务域名。**分析建议：** 采用预构建依赖镜像或隔离依赖目录；为角色闲聊禁用动态安装；按任务授予出网和目标访问能力，避免把“容器已隔离”当成供应链与网络权限审查的替代。[动态依赖实现](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/sandbox/ext_caller_code.py#L73-L177)

**源码事实：持久 Claude Code 工作区。** 另一套容器把工作区和 `.claude_home` 持久挂载，注入内部 API token、运行策略，并设置 `SKIP_PERMISSIONS=true`；端口绑定本机回环，生产环境接入主服务网络。该创建配置没有出现与一次性沙箱相同的 CPU/内存限制，不能把前者限制套用到这里。其执行器依赖外部沙箱镜像，本轮未进一步审计该镜像内部实现。[工作区容器配置](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/workspace/container.py#L176-L264)

**更关键的宿主边界：** 生成的 `api_caller` 文件含实例级 RPC secret；请求带此令牌到 `/ext/rpc_exec`。路由校验令牌后，`decode_rpc_request` 使用 `pickle.loads`，再从请求给出的频道与容器标识构建上下文并执行插件。工具展示阶段会检查启用和可用方法，RPC 的 `get_method` 则按名称遍历已加载插件，入口没有重复同样的可用性筛选。不能把“提示里没有展示某工具”当作授权控制。[令牌注入](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/sandbox/ext_caller.py#L45-L60)、[RPC 入口](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/routers/rpc.py#L21-L59)、[解码](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/rpc_service.py#L11-L20)、[方法选择](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/plugin/collector.py#L691-L720)

**分析判断：** 可读取代理文件的生成代码进入了可调用宿主 RPC 的信任域；鉴权后的 pickle 反序列化尤其不适合作为不可信代码与宿主之间的边界。各插件仍可在具体方法中自行校验，但那不能替代入口统一授权。建议替换为严格 JSON/schema、每次运行短期能力令牌，并在服务端绑定频道、方法白名单、参数和过期时间。Web 管理员角色、聊天触发配额与工具执行能力分别建模。主服务 Compose 挂载 Docker socket，主进程及宿主插件也属于高权限可信计算基，插件不是自动沙箱化的扩展。[宿主部署](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/docker/docker-compose.yml#L33-L62)

## 5. 人格与长期记忆：已有基础，缺少剧情契约

**源码事实：** 人设正文是提示编译输入；记忆是另一条可关闭主链，总开关默认 `False`。打开后会进行自动沉淀、检索注入、CC 记忆握手和后台维护，而关闭不会删除已有数据。不能从“有记忆模块”推断默认安装已经长期记忆。[人设输入](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/agent/run_agent.py#L127-L150)、[总开关](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/core/config.py#L331-L345)

段落按 `workspace_id` 隔离，区分 NA/CC 来源、episodic/semantic 认知类型，以及对话、偏好、事实、经验、决策、情绪；记录原频道、消息锚点、时间、来源种类、权重、强化时间、半衰期与失活标识。Episode 则组织相邻段落的时间经历。召回结合向量段落、实体关系与 Episode，再注入历史。这里“FACT”是抽取类别，仍可能来自角色谎言、误解或虚构叙事。[段落模型](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/models/db_mem_paragraph.py#L14-L165)、[Episode 聚合](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/memory/episode_aggregator.py#L29-L120)、[召回实现](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/memory/retriever.py#L100-L220)

工作区能绑定多个频道，意味着共享记忆是有意能力，`origin_chat_key` 是来源字段，并不自动构成频道私密授权。角色扮演应由应用建立用户、角色实例、世界、剧情分支及可见范围；同角色的公共设定与某用户的私密经历不能只靠一份共享工作区混存。[频道绑定](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/workspace/manager.py#L1107-L1135)

沉淀器会逐条存储提炼结果，捕获个别存储错误后继续，并在末尾推进消息游标。**分析风险：** 不能把游标已推进等同于所有提炼项完整入库；需记录并重放失败项。重建模块已有快照、阶段检查点、取消和进度持久化，可借鉴其运维组织，但重放原聊天时仍会重新经过模型，不保证生成完全相同的记忆。[沉淀与游标](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/memory/consolidator.py#L179-L263)、[重建实现](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/memory/rebuild.py)

**分析建议：** 增加 `reality_mode`、`canon_status`、`story_branch`、原话作者、已接受回复版本及撤销链。用户重生回复时，只有选定版本进入可巩固记忆；被撤销情节要失效其派生段落、关系和 Episode。稳定人设单独版本化，情绪不直接覆盖人格，重要共同经历不按普通短期闲聊权重自动淡忘。

## 6. 失败、取消、重启和观测

频道任务有兜底总超时与 `finally` 状态释放；一次性沙箱等待超时会 kill/delete 容器，并记录执行代码、输出、耗时和退出类型。共享目录清理由延时异步任务负责。调用 `cancel_agent_task` 只取消 Python 任务并保留后续待处理消息；沙箱等待函数没有专门的 `CancelledError` 杀容器分支，因此不能把“频道显示取消”当作容器和外部动作已经停止的证明。[频道取消](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/message_service.py#L72-L90)、[超时和清理](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/sandbox/runner.py#L265-L364)

CC 委托另有强制取消接口、后台结果观察器和启动时补取待投递结果；应用启动还恢复工作区容器、记忆重建和部分知识库任务。它们是指定组件的恢复机制，不能泛化成所有进程内聊天任务都持久恢复。[CC 客户端](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/workspace/client.py#L200-L251)、[启动恢复](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/__init__.py#L192-L229)

运行过程广播生成、重试、沙箱执行、迭代、完成和失败状态，适合管理端排障。建议贯穿 `message_id → turn_id → action_id → container/task_id → reply_id`，分别监控模型错误、待处理积压、容器残留、消息投递失败、记忆失败项和恢复重放次数。提示、代码、工具输出及思考链可能进入日志，日志访问和保留周期应按聊天数据管理，不能把调试日志当无敏感性的技术副产物。[状态广播与日志](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/agent/run_agent.py#L88-L125)、[执行记录字段](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/services/sandbox/runner.py#L293-L313)

成本应分别记录主模型生成、失败迭代、增强召回规划、记忆沉淀与 embedding，以及 CC 委托产生的调用。把这些工作都归为一次“回复请求”会掩盖后台成本；应同时观察每轮花费与记忆积压，尤其关注启动恢复和全量重建。上述只是按源码调用位置拆分预算，不是费用测算或性能实测。

## 7. 运维清单与验收场景

以下为建议清单，均未在本轮执行。

| 运维项 | 要保存或确认的内容 |
| --- | --- |
| 部署基线 | 固定主服务、Python 沙箱和 CC 沙箱镜像摘要；记录配置、人设、插件版本、模型组和迁移版本，避免仅依赖 `latest` |
| 数据备份 | PostgreSQL 业务库、Qdrant 存储/快照、`NEKRO_DATA_DIR` 下配置、上传、插件、工作区、记忆文件和重建状态；记录三者一致性时间点 |
| 升级 | 在隔离副本恢复备份后跑数据库迁移和关键对话；自动迁移默认开启，旧镜像回滚不能自动撤销数据库结构变化 |
| 权限 | Docker 主机独立、管理端认证、RPC 改为能力授权、插件审查、密钥轮换、出网控制、CC 持久目录访问检查 |
| 恢复 | 先确认存储和迁移，再恢复主服务与工作区，核对结果投递收据，清理孤儿容器，处理失败记忆和积压 |

Compose 明确把 PostgreSQL、Qdrant 放在独立命名卷，而主服务挂载数据目录；只打包一个目录并不覆盖全部数据。数据库启动迁移由 Aerich 路径管理，回滚必须把应用与数据库一起考虑。[持久卷](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/docker/docker-compose.yml#L6-L68)、[迁移](https://github.com/KroMiose/nekro-agent/blob/ea7b90eb83bd80061b2a177510c27c957f7f980d/nekro_agent/core/db_migration.py#L41-L75)

| 场景 | 通过条件 |
| --- | --- |
| 连续群聊和跨频道同时触发 | 同频道上下文不乱序，其他频道可继续；明确合并触发规则与容量上限 |
| 用户取消后立刻再发消息 | 旧容器、CC 任务和外部副作用状态可解释，新任务不会复用旧授权 |
| 发送成功后进程崩溃 | 重启不重复发送；结果投递可用持久收据核对，而非只靠内存缓存 |
| 两用户同名、私聊与群聊绑定同角色 | 角色公共设定可共享，私密信息不跨授权范围召回 |
| 改设定、撤回与重生回复 | 旧版本及派生记忆退出当前剧情，恢复后仍保持失效状态 |
| 完整恢复到新主机 | 聊天、人设、附件、向量、插件和 CC 工作区均可用，并能继续追溯来源 |

适用结论：它是行动型聊天架构的深入参考，尤其适合研究异步委托与角色行动如何回到同一对话；日常角色扮演落地前，优先补齐 RPC 信任边界、持久幂等、剧情版本与记忆可纠正机制。当前证据没有给出自然聊天质量、并发容量、安全加固效果或灾备成功率，不能据此作生产成熟度认证。
