"""一键体检：把容易出问题的地方全查一遍。

改完配置、重启前后、或者群里突然不说话了，先跑这个，比翻日志快。

用法：
    local\\venv\\Scripts\\python.exe doctor.py
"""

import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级
CFG = os.path.join(ROOT, "local", "AstrBot", "data", "cmd_config.json")
DB = os.path.join(ROOT, "local", "AstrBot", "data", "data_v4.db")
ENV = os.path.join(ROOT, ".env")
PERSONA = os.path.join(ROOT, "persona", "九条都-群聊人设.md")
PLUGINS = os.path.join(ROOT, "local", "AstrBot", "data", "plugins")

OK, WARN, BAD = "✓", "!", "✗"
results = []


def add(level, item, detail=""):
    results.append((level, item, detail))


def env_dict():
    d = {}
    if not os.path.exists(ENV):
        return d
    with io.open(ENV, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def port_open(port: int, host="127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def check_keys(env):
    for name, label in (("DEEPSEEK_API_KEY", "DeepSeek"), ("ZHIPU_API_KEY", "智谱视觉")):
        v = env.get(name, "")
        if not v:
            add(BAD, f"{label} Key", "空的，去 .env 里填")
        elif v != v.strip():
            add(BAD, f"{label} Key", "首尾有空白字符，会导致鉴权失败")
        else:
            add(OK, f"{label} Key", f"{len(v)} 位")


def check_ports():
    for port, label in ((6185, "AstrBot 后台"), (6199, "QQ 反向 WS"), (6099, "NapCat 后台")):
        add(OK if port_open(port) else WARN, f"端口 {port} {label}",
            "在监听" if port_open(port) else "未监听（AstrBot 没启动？）")


def check_cfg():
    if not os.path.exists(CFG):
        add(BAD, "配置文件", "找不到 cmd_config.json")
        return None
    d = json.load(io.open(CFG, encoding="utf-8-sig"))

    persona_cfg = d.get("agent_runner", {}).get("config", {}).get("persona", {})
    add(OK if not persona_cfg.get("safety_mode") else WARN, "Safe Mode",
        "已关闭" if not persona_cfg.get("safety_mode") else "开着，会拉向客服腔")

    ltm = d.get("provider_ltm_settings", {})
    add(OK if ltm.get("image_caption") else WARN, "图片描述",
        "开启" if ltm.get("image_caption") else "关闭")

    prov = {p["id"]: p for p in d.get("provider", [])}
    vision = prov.get("zhipu-vision")
    add(OK if vision and vision.get("enable") else WARN, "视觉 provider",
        "启用" if vision and vision.get("enable") else "未启用")

    admins = d.get("admins_id", [])
    has_qq = any(str(x).isdigit() for x in admins)
    add(OK if has_qq else WARN, "管理员 QQ", f"{admins}" + ("" if has_qq else "（没有QQ号，/reset 用不了）"))

    rl = d.get("platform_settings", {}).get("rate_limit", {})
    add(OK if rl.get("strategy") == "discard" else WARN, "限流策略",
        f"{rl.get('count')}/{rl.get('time')}s {rl.get('strategy')}")

    ar = ltm.get("active_reply", {})
    ar_enabled = ar.get("enable", False)
    will_installed = os.path.isdir(os.path.join(PLUGINS, "willingness_gate"))
    if not ar_enabled and will_installed:
        add(OK, "主动插话", "意愿评估版（willingness_gate）")
    elif ar_enabled:
        add(OK, "主动插话", f"内置随机 {int(ar.get('possibility_reply', 0) * 100)}%")
    else:
        add(WARN, "主动插话", "已关闭（且未装 willingness_gate）")

    ps = d.get("provider_settings", {})
    if ps.get("web_search"):
        prov = ps.get("websearch_provider", "?")
        keys = ps.get(f"websearch_{prov}_key") or []
        has_key = bool(keys and str(keys[0]).strip())
        if prov == "deepseek" and not has_key:
            add(WARN, "联网搜索", "已开启但没填 key")
        else:
            add(OK, "联网搜索", f"开启（{prov}）" if has_key else f"开启（{prov}，无 key）")
    else:
        add(OK, "联网搜索", "关闭")

    cs = d.get("content_safety", {}).get("internal_keywords", {})
    add(OK if not cs.get("enable") else WARN, "关键词过滤",
        "关闭" if not cs.get("enable") else "开启")

    return d


def check_persona():
    if not os.path.exists(PERSONA) or not os.path.exists(DB):
        add(WARN, "人设", "文件或数据库缺失")
        return
    text = io.open(PERSONA, encoding="utf-8").read().strip()
    try:
        c = sqlite3.connect(DB)
        row = c.execute("select system_prompt from personas where persona_id='miyako'").fetchone()
        c.close()
    except Exception as e:
        add(WARN, "人设", f"读数据库失败: {e}")
        return

    if not row:
        add(BAD, "人设", "数据库里没有 miyako")
        return
    if row[0].strip() == text:
        add(OK, "人设", f"{len(text)} 字，文件与库一致")
    else:
        add(WARN, "人设", f"文件 {len(text)} 字 / 库 {len(row[0])} 字 —— 改了没同步，双击 apply-persona.bat")


def check_plugins():
    required = {
        "caption_filter": "图片/视频描述",
        "sticker_pack": "表情包库",
        "miyako_tts": "语音官方 Provider（翻译+情绪）",
        "knowledge_card": "设定速查卡",
        "willingness_gate": "发言意愿评估",
        "memory_distill": "群友画像+滚动摘要",
    }
    for name, label in required.items():
        path = os.path.join(PLUGINS, name, "main.py")
        add(OK if os.path.exists(path) else BAD, f"插件 {name}", label)

    idx = os.path.join(PLUGINS, "sticker_pack", "index.json")
    if os.path.exists(idx):
        try:
            data = json.load(io.open(idx, encoding="utf-8"))
            add(OK, "表情包库", f"{len(data.get('items', []))} 张 / {len(data.get('senders', {}))} 个群友")
        except Exception:
            add(WARN, "表情包库", "index.json 读不动")
    else:
        add(OK, "表情包库", "0 张（还没开始攒）")


def check_ffmpeg():
    cands = [os.environ.get("FFMPEG_PATH", ""), "ffmpeg",
             r"D:\ImageMagick-7.0.10-Q16\ffmpeg.exe"]
    for c in cands:
        if not c:
            continue
        if os.path.isabs(c) and os.path.exists(c):
            add(OK, "ffmpeg", os.path.basename(c))
            return
        if not os.path.isabs(c) and shutil.which(c):
            add(OK, "ffmpeg", "PATH 里")
            return
    add(WARN, "ffmpeg", "没找到，视频抽帧用不了")


def check_tts():
    try:
        sys.path.insert(0, ROOT)
        import tts_setup  # noqa: PLC0415

        d = tts_setup.load_cfg()
        tts = d.get("provider_tts_settings", {})
        if tts.get("enable"):
            add(WARN, "语音", "内核 TTS 开着——会和 miyako_tts 双重语音，请关掉")
        elif os.path.isdir(os.path.join(PLUGINS, "miyako_tts")):
            sov, gpt, ref, _ = tts_setup.discover()
            if sov and gpt and ref:
                add(OK, "语音", "台词制（miyako_tts）——LLM 直接产出日语台词")
            else:
                add(WARN, "语音", "miyako_tts 在但权重/参考音不全")
        else:
            add(WARN, "语音", "内核 TTS 关了且 miyako_tts 未安装， bot 是哑的")

        # 启动顺序：AstrBot 只在启动时推一次权重，9880 不通就会用默认模型
        bot_up, gsv_up = port_open(6185), port_open(9880)
        if bot_up and not gsv_up:
            add(BAD, "启动顺序",
                "AstrBot 在跑但 9880 没起 —— 语音初始化已失败，开 GSV 后必须重启 AstrBot")
        elif bot_up and gsv_up:
            add(OK, "启动顺序", "AstrBot 和语音服务都在跑")
        elif gsv_up:
            add(OK, "启动顺序", "语音服务就绪，启动 AstrBot 即可")
        else:
            add(WARN, "启动顺序", "两个都没起，先 start-gsv.bat 再 start-astrbot.bat")
    except Exception as e:
        add(WARN, "语音", f"检查失败: {e}")


def main():
    env = env_dict()
    print("=" * 62)
    print(" AstrBot 体检")
    print("=" * 62)
    check_keys(env)
    check_ports()
    check_cfg()
    check_persona()
    check_plugins()
    check_ffmpeg()
    check_tts()

    for level, item, detail in results:
        print(f"  {level}  {item:<22} {detail}")

    bad = sum(1 for l, _, _ in results if l == BAD)
    warn = sum(1 for l, _, _ in results if l == WARN)
    print("=" * 62)
    print(f" 问题 {bad} 项，提醒 {warn} 项，其余正常")
    if bad:
        print(" → 先处理 ✗ 的，那些是会直接不工作的。")
    elif warn:
        print(" → 没有硬故障，`!` 的多半是没启动或没配置，按提示来即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
