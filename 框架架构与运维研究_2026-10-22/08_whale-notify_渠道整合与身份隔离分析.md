# whale-notify：渠道整合、身份隔离与可靠回复分析

核验日期：2026-10-22。背景仅来自指定前期报告，未读取用户项目其他文件。实际阅读 `Mochabafey/whale-notify` 的 `main`，commit `531e73a50d734532f100649422526a836fe9215f`，插件 `package.json` 版本 `0.3.0`；宿主对照为 DSH `master` commit `687f282e8625c6b8d11ff58211a90524be2e4317`。先用 GitHub 连接器读取分支、文件树和 `memory.js`，再在系统 TEMP 浅克隆官方仓库静态阅读。没有安装、运行验证脚本或连接 QQ/飞书。[whale 版本证据](https://github.com/Mochabafey/whale-notify/commit/531e73a50d734532f100649422526a836fe9215f)、[插件清单](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/package.json)。

“源码事实”指所读快照的调用关系；“README 主张”是作者公开说明；“建议”是本报告的架构推导。仓库中的作者实测、修复记录不等于本报告已复现。项目名称相近，仍不能据此认定它就是前期报告提到的“鲸鲸”。

## 1. 结论与适用位置

whale-notify 是很有参考价值的 Agent 渠道桥接样本：它把 QQ、飞书、邮件、定时发送、简易记忆和跨插件工具放在一起，能看见一次外部交互如何走入 DSH。但源码的中心是“把外部指令交给现有桌面 Agent”，尚未形成多群、多用户角色聊天产品所需的强制身份隔离和可靠消息事务。

最应区分的三点是：按群过滤近期记忆不等于隔离整个 Session；“只读”文字提示不等于工具执行权限；连接重连/入站去重不等于回复恰好发送一次。原报告对这些能力采用项目说明措辞是合理的，深入设计时不能继续把它们当成已实现的产品保证。[README 能力说明](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/README.md)、[主调用链](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js)。

## 2. 源码地图

| 文件 | 职责及本次核验重点 |
| --- | --- |
| `lib/index.js` | 工具注册、ACL、目标 Agent 选择、入站注入、重连、配置与自检 |
| `lib/qq.js` | OneBot HTTP 发信、反向 WebSocket 收信、消息归一化、握手鉴权 |
| `lib/feishu.js` | 官方 SDK 长连接、文字事件解析、tenant token、IM 发信 |
| `lib/config.js` | `$ENV:` 展开、渠道解析、白名单、分条 |
| `lib/friendmode.js`、`memory.js` | 群触发风格、黑名单、群记忆、统一文档库 |
| `lib/registry.js`、`playbooks.js` | 发现本会话工具、嵌套调用、操作手册与提示摘要 |
| `lib/channels.js`、`scheduler.js` | 发送路由、协议错误、定时汇报 |
| `lib/ask.js`、`imap.js` | 邮件决策持久化、回信匹配与会话恢复 |
| `cordis.patch.yml`、`examples/dsh-preset-jingyuniang/cordis.patch.yml` | profile 配置与鲸鱼娘提示词示例 |

文件均位于[固定版本插件目录](https://github.com/Mochabafey/whale-notify/tree/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify)；关键事实在下文链接到各自文件。

## 3. QQ 与飞书完整入站链

### QQ：接收、群模式、会话投递

源码通过 `ws` 启动反向 WebSocket server，接收 OneBot 事件，归一化为私聊/群聊、userId、groupId、messageId、正文、昵称和触发标记。图片主要是占位符，不能把它当成完整多模态聊天实现。`isReply` 只检查是否存在任意 reply 段，并未验证引用目标确实是机器人；缺 selfId 时，任意非全体 @ 可以退化成 atMe。由此，README 的“被回复触发”应理解为当前实现的宽松触发。[QQ 归一化及接收源码](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/qq.js)。

`handleQQMessage` 分三条路径。普通群模式和私聊走 `checkAccess`；群友模式开启后改走群/用户黑名单，不再调用普通白名单 ACL。群友模式先记录未拉黑者的所有群消息，仅在 atMe、isReply 或包含昵称时注入。它再拼入风格与本群近期记忆，并提示模型调用 `notify(channel:"qq",groupId:原群)` 回复。因而“名单外无反应”只适用于普通 ACL 路径，不能覆盖已开启的群友模式。[处理分支](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L709-L768)。

### 飞书：文字事件、过滤、白名单

飞书使用官方 SDK `WSClient` 订阅 `im.message.receive_v1`，提取 text 并还原 mention 占位符。主模块先做消息 ID 去重，再排除机器人自身事件、检查 chatTypes；当配置目标类型为 chat_id 时，群聊必须匹配目标群，私聊可进入，最后检查发信人 ACL。它不实现 QQ 群友模式那套 @ 决策，允许群里的消息经过身份过滤后可以直接成为任务。[SDK 适配](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/feishu.js)、[飞书处理顺序](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L568-L618)。

### 两者汇合：并非按联系人建立 Session

两条路径最终都调用 `injectToAgent → pickTarget → agent.followup`。目标依次尝试显式 targetSession、全插件共享的 lastInjectedSession、sessionQuery 的活跃会话顺序、按活跃时间排序的根 Agent。显式 Session 不在线时会记日志并继续自动选择，不会因目标失效而停止。正常自动选择避开子 Agent，但无根 Agent 时可回退存活集合。[目标选择及注入](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L400-L521)。

源码没有在这里按 `(平台,账号,群/私聊,联系人)` 建立 Session 映射，也不会恢复一个冷的 targetSession；没有存活 Agent 就注入失败。各渠道虽能分别指定目标，但单个 QQ 配置的所有群和私聊共享同一选择路径。lastInjectedSession 只在内存，重启后重新自动选择。因此可复用的是接入流程，不能直接复用其桌面“最可能正在看哪个会话”的路由策略。

## 4. 身份、记忆与 prompt 可信边界

`memory/friend/memory.jsonl` 是所有群共用文件；`readFriendMemory(limit,groupId)` 在解析最近全局 500 行后筛选 groupId，并保留 kind=system 行。`buildFriendPrompt` 确实传入当前群 ID，故“近期群记忆按群过滤”有源码依据。但热闹群可挤掉冷门群的候选窗口，历史 Session 中已注入的其他群消息也不会被过滤掉。[记忆读取](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/memory.js)、[群提示构造](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/friendmode.js)。

统一文档库 conversations/summaries 按标题、标签和正文子串打分，没有用户/群 ACL；`recall_memory` 还可列其他非子代理会话，并在显式 includeTranscript 时读取最近对话原文注入当前 Agent。源码有“背景参考”提示和记忆根目录范围校验，但没有把调用人的平台身份带入文档或 Session 访问校验。这意味着只要共享 Agent 暴露相应工具，群内输入可能影响对私聊/桌面历史的调用决策。[召回工具](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L1067-L1169)、[文档读写](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/memory.js)。

`readOnlyUsers` 的真实执行是给正文加“只读消息”前缀和禁止修改的文字；群友 readOnly 也一样。未看到对应工具 guard、restriction 或按消息绑定的 capability。来源 `plugin:tool-notify` 有助审计，但文本里的发信人、昵称、群历史和“请发回这里”仍和外部原文一起组成 user-role 消息。恶意原文可与这些提示争夺模型行为；“只读”不能承担安全授权。[注入代码](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L497-L521)。

还存在明确的入口边界：代码默认 ACL 为 open，而随包 patch 显式配置 whitelist；部署结果取决于实际使用的配置。QQ 反向 WS 在配置 accessToken 后，若提取不到凭证仍放行，只有非空且不匹配的 token 才拒绝。patch 默认 wsHost=127.0.0.1，有助限制暴露；接收实现也允许 0.0.0.0 或未传 host，不能把令牌配置本身当严格鉴权保证。[ACL 解析](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/config.js#L262-L292)、[握手代码](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/qq.js#L142-L169)、[随包配置](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/cordis.patch.yml)。

## 5. 跨插件工具：复用了宿主权限，但权限主体仍是 Agent

`plugin_tools` 能列可用工具、查手册、顺序调用多步并引用前步规范值。`callTool` 检查工具对当前 Agent 可见，拒绝直接调用自己，传递 agent、signal、parent token、rootCallId，再调用宿主 `tools.execute`。对照 DSH 注册表，pre-execute、单调 guard 和执行包装器确实仍会运行；这是值得保留的做法。[跨插件执行](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/registry.js)、[调用参数传递](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L1785-L1832)、[宿主执行管线](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/tools/src/index.ts#L1492-L1598)。

需要修正的推论是：这些限制区分的是 Agent 可见工具，不是 QQ 发信人的权限。当桌面主人、群友和只读用户都进入同一 Agent，它们面对同一能力集合。settings、friend_mode、save_memory、recall_memory 和跨插件工具也没有在各自 execute 里核验原始发信人。角色聊天应为普通群聊设独立 Agent/preset，限制运维、配置和跨会话召回；需要高权限行动时通过可信控制通道交给另一个执行 Agent。

README 声称嵌套深度有上限；源码确有 MAX_DEPTH 检查，但主入口每步都传 depth:0，不能据此证明经过其他工具反向调用形成的任意循环也被全链路计数。本次未验证互递归场景。手册和系统提示摘要改善工具可用性，不会新增隔离能力。[深度参数实现](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/registry.js)、[提示摘要注册](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L370-L392)。

## 6. 回复路由、去重、重试与重启

回复链并非“模型输出后自动投递”：入站正文附一段回信提示，模型需主动调用 notify。notify 选择渠道，经 trySend 分条后顺序发 HTTP 请求；QQ 走 OneBot send_private_msg/send_group_msg，飞书走 IM API。没有回复目标 capability，也没有自动把原始 messageId 绑定到 sendText 的 replyTo。[notify 工具](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L930-L1017)、[渠道发送](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/channels.js)。

QQ 有一个需要优先验收的具体路由条件：channels.js 先取 `extra.groupId ?? entry.groupId`，只要存在就选群目标，私聊 to 仅在无群目标时使用。因此配置了默认 groupId，模型按私聊提示只传 to，仍可能发到默认群。这个条件从代码直接可推导，尚未做平台复现；产品层必须让“显式私聊目标”排除默认群，而不是依赖提示词补救。[QQ 目标优先级](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/channels.js#L178-L200)。

可靠性边界应分开记录：

| 机制 | 已有事实 | 不能推出的保证 |
| --- | --- | --- |
| 飞书 seen | 处理前记 ID，最多 500 条，延迟约400ms写 JSON | 入队失败后可靠重投；崩溃窗口无重复 |
| QQ 收信 | 归一化保留 messageId，接收主链未使用去重表 | NapCat 重投不会重复执行 |
| 飞书重连 | SDK autoReconnect；启动失败另有退避，最多6次，effect关闭最新连接 | 长时间离线后一定恢复或补齐全部消息 |
| 发信 | 分条逐个 await；返回渠道成功/失败 | 事务发送、持久 outbox、部分成功后的安全重试 |
| 邮件 pending | 决策 JSON 落盘，启动按sessionId重绑，默认24小时过期 | 冷会话自动恢复、磁盘写入必达、回信一定授权 |
| 定时汇报 | lastFired Map按名称/分钟去重，发送前标记 | 跨重启去重、失败重试、休眠补发 |

对应证据：[seen 与重连](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L107-L162)、[QQ 接收](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/qq.js)、[分条发送](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/channels.js)、[pending 恢复](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/ask.js)、[汇报调度](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/scheduler.js)。

飞书 seen 在过滤和成功入队前就 add，入队失败也保留；反过来异步保存失败又可能在重启后重复。分条第1条成功、第2条失败时，整体错误没有持久分片回执，整条重试可能重复第1条。飞书发送返回 messageId、QQ 也返回 message_id，但 trySend 未把这些存为业务 outbox 回执。[seen 顺序](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L568-L618)、[底层发送结果](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/feishu.js#L77-L100)。

邮件回信还有可信边界：imap 按主题决策 ID 匹配，pending 保存的收件人未在 pollAndInject 中用于发信人校验；匹配后先删除 pending，再判断原 Agent 是否存在，孤儿回复会被跳过。注入还显式使用 source:user。故“邮件审批”应理解为邮件问答接口，不能直接替代宿主审批协议。[回信匹配](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/imap.js)、[删除与注入顺序](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/ask.js#L164)。

## 7. 角色聊天的复用与改造建议

保留协议适配、环境变量解析、分条、工具发现和自检思路；重新设计身份路由和可靠交付。推荐路径为：平台事件进入持久 inbox，以 account/conversation/messageId 去重；策略层验证可信 sender 与权限；绑定独立角色 Session；发言决策明确是否回应；模型只生成回复内容或受限动作；发送器从原 envelope 取得不可伪造的目标，写 outbox 并逐片记录回执。提示词负责风格，程序负责目标和授权。

群关系记忆至少应含主体范围、来源消息、事实/猜测、更新时间、纠正记录和可撤销状态。私聊默认只在对应关系中召回；跨群共享的角色自我记忆需显式分类。把鲸鱼娘人设当示例模板，而非固定产品人格；把运维 playbook 留给专用执行者。whale、selfwake、meow-memory 若同时使用，应分别指定谁决定发言、谁拥有长期记忆写入，先验证事件顺序与版本，不能预设可无冲突拼装。

## 8. 运维、备份升级与验收

备份范围包括实际 profile 组合和插件锁定版本、`memory/`、`knowledge/`、`friendmode/config.json`与`prompts.md`、DSH Session、`logs/notify-pending.json`、`logs/feishu-seen.json`。日志 notify.log 含入站文本片段，应按关系范围控制访问和保留期限。配置编辑走 configEditor 会重载插件；应核对连接释放、内存去重重置和待办保存，不能只检查界面提示“已生效”。当前 package 没有 engines.dsh，DSH tools peer 为 `*`，这一宽泛声明不能证明未来宿主兼容。[包声明](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/package.json)、[配置编辑路径](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L1228-L1402)。

观测保留 whale_check 和结构化日志的长处，增加“已接收/已授权/已入队/已生成/部分发送/已送达”的关联状态。当前 connections 计数在消息回调递增，应避免把它解释为真实 WS 连接数。静态脚本 `verify-notify.mjs` 使用模拟渠道和假工具注册表，有协议回归参考价值；本次未运行，也不能以作者测试数推断真实 QQ/飞书恢复已通过。[自检与状态](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/plugins/dsh-whale-notify/lib/index.js#L687-L911)、[验证脚本](https://github.com/Mochabafey/whale-notify/blob/531e73a50d734532f100649422526a836fe9215f/verify-notify.mjs)。

部署复核应从实际配置快照开始：白名单变量是否展开成预期 ID、群友模式是否开启、QQ 监听地址是否明确、默认目标是否与聊天回复冲突、当前 Agent 到底暴露哪些工具。备份恢复应在副本里分别检查群记忆、跨会话文档、pending 和 seen；只恢复其中一部分可能让旧消息重新执行或让回复丢失关联。升级后先用测试账号和测试群走一次完整收发及断线恢复，再开放真实用户。以上是实施建议，本次仅完成源码核验。

| 待验收场景 | 核心判据 |
| --- | --- |
| 默认群已配置，QQ私聊要求回复 | 不发默认群，发送目标由原始私聊绑定 |
| 群A/群B/主人私聊交错输入 | Session、召回和回复三层均不泄漏 |
| 白名单外成员在群友模式@机器人 | 行为符合显式群策略，不误继承主人执行权 |
| 只读消息要求改配置/SSH/读其他会话 | 程序拒绝，嵌套工具也不能绕过 |
| 缺/错 token、任意引用他人消息 | 接入拒绝与触发规则准确，日志可辨原因 |
| 无活跃Session、targetSession离线 | 固定排队或明确失败，不降级到错误会话 |
| 重投、断网、部分分条成功、进程崩溃 | 不重复执行；不确定送达可核对与恢复 |
| 定时分钟内重载、跨时区/休眠 | 是否补发/跳过有明确策略并持久记录 |

这些场景尚未实测。当前证据足以把 whale-notify 作为“桌面 Agent 接入外部渠道”的学习样本，并明确指出路由、授权和交付需要重做的边界；不足以认证其作为多人长期角色机器人的隔离性、持续运行稳定性或与其他记忆/主动性插件的组合兼容性。
