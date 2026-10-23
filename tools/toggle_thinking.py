"""切换 DeepSeek 的思考模式。

用法：
    local\\venv\\Scripts\\python.exe toggle_thinking.py off
    local\\venv\\Scripts\\python.exe toggle_thinking.py low
    local\\venv\\Scripts\\python.exe toggle_thinking.py high

改完要重启 AstrBot 才生效。
"""

import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级
CFG = os.path.join(ROOT, "local", "AstrBot", "data", "cmd_config.json")

MODES = {
    "off": ({"thinking": {"type": "disabled"}}, "关闭思考"),
    "low": (
        {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
        "轻度思考（推荐尝鲜档）",
    ),
    "high": (
        {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
        "深度思考",
    ),
}


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if mode not in MODES:
        print("用法: toggle_thinking.py [off|low|high]")
        return 2

    extra, label = MODES[mode]

    if not os.path.exists(CFG):
        print(f"[ERROR] 找不到配置：{CFG}")
        return 1

    shutil.copyfile(CFG, CFG + ".bak")

    with io.open(CFG, encoding="utf-8-sig") as f:
        cfg = json.load(f)

    prov = cfg["provider"][0]

    # 思考模式的推理 token 也算在 max_tokens 里，上限太小吃不消。
    old_extra = prov.get("custom_extra_body") or {}
    old_max = old_extra.get("max_tokens") or prov.get("max_tokens")
    if mode != "off" and isinstance(old_max, int) and old_max < 300:
        print(f"[WARN] 原来的 max_tokens={old_max} 太小，开思考会返回空消息，已清掉。")
        prov.pop("max_tokens", None)

    prov["custom_extra_body"] = extra

    with io.open(CFG, "w", encoding="utf-8-sig") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    print(f"已切换为：{label}")
    print(f"custom_extra_body = {json.dumps(prov['custom_extra_body'], ensure_ascii=False)}")
    print()
    print("重启 AstrBot 生效：双击 start-astrbot.bat")
    if mode != "off":
        print("提示：思考的推理 token 也计入 max_tokens，别把回复上限设得太小。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
