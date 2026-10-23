# 复现指南（Reproduce）

按本文档走，能在一台干净的 Windows 机器上得到**和作者本机一致的效果**：
同一套人设、同一套插件参数、同一个声音。

> 唯一需要你自己准备的：DeepSeek API Key、一个 QQ 小号、以及**语音权重**
> （150MB×2，放在 GitHub Releases，见第 5 步）。

---

## 0. 版本锁定表（版本不对，行为会不一样）

| 组件 | 版本 | 备注 |
| --- | --- | --- |
| Windows | 10 / 11 | 脚本是 .bat，Linux 需自己改写 |
| Python | 3.13 | AstrBot 4.29.1 的 venv 里就是 3.13 |
| **AstrBot** | **4.29.1** | 插件依赖它的内部接口（provider 注册、pipeline 钩子），大版本别乱升 |
| **NapCat** | **4.18.38** | 协议端，与 QQ 9.9.36 兼容 |
| QQ | 9.9.36-53644 | 版本太新 NapCat 可能挂不上 |
| **GPT-SoVITS** | **v2ProPlus（20250604）** | 权重是 v2ProPlus 架构，v2/v3 加载不了 |
| ffmpeg | 任意较新版本 | 视频识图用；脚本里兜底路径 `D:\ImageMagick-7.0.10-Q16\ffmpeg.exe`，位置不同要改 `caption_filter/main.py` |
| 磁盘 | ≥ 6GB | venv 0.5G + NapCat 0.1G + 权重 0.7G + GSV 本体 2G+ |

---

## 1. 目录结构（必须保持）

```
qq-bot/
├── 启动.bat
├── persona/                     人设卡 + 设定速查
├── tools/                       所有脚本
├── voice/
│   ├── ref/                     情绪参考音（仓库自带）
│   └── weights/                 ← 你要从 Release 放进来（第 5 步）
└── local/
    ├── venv/                    ← Python 环境（第 2 步创建）
    ├── AstrBot/                 ← AstrBot 4.29.1（第 3 步）
    │   └── data/
    │       ├── plugins/         5 个自研插件（仓库自带）
    │       ├── cmd_config.repro.json   ← 调好的配置模板
    │       └── cmd_config.json         ← 由脚本生成（不入库）
    └── NapCatShell/             ← NapCat（第 4 步）
```

---

## 2. 准备 Python 环境

```bat
cd /d E:\氛围传输素材\qq-bot
py -3.13 -m venv local\venv
local\venv\Scripts\python.exe -m pip install -U pip
```

> AstrBot 本体由第 3 步安装，会装进这个 venv。

---

## 3. 安装 AstrBot 4.29.1

```bat
local\venv\Scripts\python.exe -m pip install astrbot==4.29.1
```

装完后把包内容铺到 `local/AstrBot`（或者直接用 `astrbot init` 让它在该目录初始化）：

```bat
cd local\AstrBot
..\venv\Scripts\astrbot.exe init
```

首次 `init` 会生成 `data/cmd_config.json`。**接着用第 6 步的脚本来覆盖成调好的配置。**

---

## 4. 安装 NapCat 4.18.38

1. 下载 NapCat Shell 4.18.38，解压到 `local/NapCatShell/`
2. 用 `tools\launch-napcat.bat` 拉起（它会自动找 QQ.exe 并注入）
3. 首次需要扫码登录**机器人小号**
4. NapCat 反向 WS 指向 `ws://127.0.0.1:6199/ws`（配置在 `local/NapCatShell/config/onebot11_<QQ号>.json`，
   仓库不带这个文件，需要自己在 NapCat 面板里加一个「WebSocket 客户端」）

---

## 5. 语音权重（必须手动下载）

GitHub 单文件上限 100MB，权重每个 150MB+，所以放在 **Releases**：

1. 打开仓库右侧 **Releases** → 最新版本
2. 下载两个文件（**文件名必须一致**，配置里写死了）：
   - `11g-miyako-e40.ckpt`（GPT 权重，约 148MB）
   - `11g-miyako_e40_s3480.pth`（SoVITS 权重，约 165MB）
3. 放进 `voice/weights/`

> 用的是 11 组训练的 e40（v2ProPlus）。想换别的轮次，改 `cmd_config.json`
> 里 `gsv_source.gpt_weights_path / sovits_weights_path` 即可。
>
> 参考音 `voice/ref/*.wav` 仓库自带（normal/happy/shy/sad + miyako_ref）。

再装 GPT-SoVITS 本体（约 2~3GB）：

1. 下载 GPT-SoVITS v2ProPlus 整合包，解压到 `F:\GPT-SoVITS-v2pro-20250604`
   （路径不同就改 `tools/start-gsv.bat` 里的 `GSV_HOME`）
2. `tools\start-gsv.bat` 会跑 `runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880`

---

## 6. 一键铺配置 + 人设

```bat
local\venv\Scripts\python.exe tools\setup_repro.py
```

它做四件事（幂等，可重复跑）：

1. 检查目录结构
2. 没有 `.env` 就从 `.env.example` 生成 → **你去填 `DEEPSEEK_API_KEY` / `ZHIPU_API_KEY`**
3. 没有 `cmd_config.json` 就用 `cmd_config.repro.json` 生成，并把
   `__PROJECT_ROOT__` 换成本机真实路径；已有配置修路径，并仅对已知无效`change_me`+空hash组合备份后修复
4. 把人设写进 `data_v4.db` 的 `personas` 表（需要先启动过一次 AstrBot 建库）

生成出来的 `cmd_config.json` 中需要你填写：

| 字段 | 改成 |
| --- | --- |
| `provider_settings.websearch_deepseek_key` | 你的 DeepSeek key（联网搜索用） |
| 后台密码 | 首次启动查看AstrBot日志中的随机初始密码，登录后改密；不要把明文填进`dashboard.password` |
| `admins_id` | 你的 QQ 号（`/reset`、`/都记忆` 等管理命令靠它） |

---

## 7. 启动与验收

按顺序：`tools\start-gsv.bat` → `tools\start-astrbot.bat` → `tools\launch-napcat.bat`

**验收清单**（对照作者本机状态）：

| 检查项 | 期望 |
| --- | --- |
| `tools\doctor.bat` | 全部 `✓`，0 问题 |
| AstrBot 日志 | `[miyako_tts] 台词制语音已生效`、`[will] 注意力门控已启用`、`[mem] v2启动` |
| 群聊 @ 她 | 中文文字 + **日语语音**（语音不是机翻，带语气词） |
| 不 @ 正常聊天 | 冷态等间隙打包判断；提到后关注180秒；允许模型继续旁听 |
| 发图片 | 她能看到图片内容（GLM-4V-Flash） |
| 问"最近有什么新闻" | 她会调 `web_search_deepseek` 再回答 |
| `/都记忆`（管理员） | 返回群友画像（跑几小时才有内容） |
| `/都忘掉 某人 关键词` | 删掉记错的事 |

---

## 8. 已知的“不可复现”部分

| 项 | 原因 | 影响 |
| --- | --- | --- |
| `data_v4.db` | 含作者群聊记录，不入库 | 复现者从空库开始，人格/画像需重新积累 |
| `sticker_pack/pool` | 群友表情包图片 | 新库从 0 开始收集 |
| NapCat 扫码 | 需要机器人小号 | 必须自己扫码 |
| `voice/ab_test/*.wav` | 试听产物，3.4MB | 不影响功能 |
| 情绪参考音的具体挑选 | 来自作者训练集 | 已随仓库提供 `voice/ref/*.wav`，效果一致 |

---

## 9. 排查

| 现象 | 先看 |
| --- | --- |
| 语音不是她的声音 | 权重路径不对 / AstrBot 启动时 9880 没起来（顺序反了） |
| 完全没语音 | `provider_tts_settings.enable` 必须为 `false`（由 miyako_tts 接管语音） |
| 双重回复 | `active_reply.enable` 必须为 `false`（由 willingness_gate 接管插话） |
| 她变得很闷 | 看决策日志的对象/action/score，再检查`COLD_THRESHOLD` / `WARM_THRESHOLD`（默认7/5）及预算 |
| 她太吵 | 调高阈值，或增加`COLD_COOLDOWN` / `WARM_COOLDOWN`，不要启用内置随机插话 |

升级已有部署请先按 [AGENT_HANDOFF_2026-10-23.md](AGENT_HANDOFF_2026-10-23.md) 备份与迁移；
特别检查旧配置的 `platform_settings.rate_limit.count=0`，避免在插件前吞掉@。

更细的排障见 `启动与故障处理.md` 和 `使用文档.md`。
