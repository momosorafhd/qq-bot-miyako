"""开启 / 关闭图片识别，并检查配置状态。

用法：
    local\\venv\\Scripts\\python.exe vision_setup.py on
    local\\venv\\Scripts\\python.exe vision_setup.py off
    local\\venv\\Scripts\\python.exe vision_setup.py status
"""

import io
import json
import os
import shutil
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级
CFG = os.path.join(ROOT, "local", "AstrBot", "data", "cmd_config.json")
ENV = os.path.join(ROOT, ".env")
VISION_ID = "zhipu-vision"


def probe_key(key: str) -> tuple[bool, str]:
    """拿 key 真打一次智谱接口，别等跑起来才 401。"""
    body = json.dumps(
        {
            "model": "glm-4v-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 8,
        }
    ).encode()
    req = urllib.request.Request(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status == 200:
                return True, "接口验证通过"
            return False, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:160]
        except Exception:
            pass
        if e.code == 401:
            return False, "Key 无效或已过期（智谱返回 401）"
        return False, f"HTTP {e.code} {detail}"
    except Exception as e:
        # 网络问题不拦，交给运行时
        return True, f"（联网校验跳过：{type(e).__name__}）"


def read_env():
    d = {}
    with io.open(ENV, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def load_cfg():
    with io.open(CFG, encoding="utf-8-sig") as f:
        return json.load(f)


def save_cfg(d):
    shutil.copyfile(CFG, CFG + ".bak")
    with io.open(CFG, "w", encoding="utf-8-sig") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def set_enabled(d, on):
    for p in d.get("provider", []):
        if p.get("id") == VISION_ID:
            p["enable"] = on
    ltm = d["provider_ltm_settings"]
    ltm["image_caption"] = on
    ltm["image_caption_provider_id"] = VISION_ID


def cmd_status():
    env = read_env()
    key = env.get("ZHIPU_API_KEY", "")
    d = load_cfg()
    prov = next((p for p in d.get("provider", []) if p.get("id") == VISION_ID), None)
    ltm = d["provider_ltm_settings"]

    print(f"  ZHIPU_API_KEY      : {'已填 ' + str(len(key)) + ' 位' if key else '空'}")
    if key and key != key.strip():
        print("  [!] Key 首尾有空白字符，会导致请求失败，请重新粘贴")
    print(f"  provider 已启用     : {bool(prov and prov.get('enable'))}")
    print(f"  image_caption      : {ltm.get('image_caption')}")
    print(f"  caption provider   : {ltm.get('image_caption_provider_id')}")

    ready = bool(key) and key == key.strip() and prov and prov.get("enable") and ltm.get("image_caption")
    print()
    print("  结论:", "图片识别已开启" if ready else "图片识别未开启")
    return 0


def cmd_on():
    env = read_env()
    key = env.get("ZHIPU_API_KEY", "")
    if not key:
        print("[ERROR] .env 里的 ZHIPU_API_KEY 是空的。")
        print("        1. 打开 https://bigmodel.cn 注册")
        print("        2. 控制台 -> API Keys -> 新建，复制")
        print("        3. 粘到 .env 里 ZHIPU_API_KEY= 后面，存盘")
        print("        4. 再运行一次")
        return 1
    if key != key.strip():
        print("[ERROR] Key 首尾带了空白字符，会请求失败。")
        print("        把 .env 里那一行删掉重新粘贴，注意别带空格。")
        return 1

    print("正在用这个 Key 试连智谱……")
    ok, msg = probe_key(key)
    print(f"  {msg}")
    if not ok:
        print()
        print("[ERROR] 这个 Key 用不了，没有开启。")
        print("        去 https://bigmodel.cn 控制台确认：Key 是否被删除/过期、实名是否完成。")
        return 1

    d = load_cfg()
    set_enabled(d, True)
    save_cfg(d)
    print("已开启图片识别（智谱 GLM-4V-Flash）")
    print("只描述表情包和 @ 她的图，其余图片跳过。")
    print()
    print("重启 AstrBot 生效：双击 start-astrbot.bat")
    return 0


def cmd_off():
    d = load_cfg()
    set_enabled(d, False)
    save_cfg(d)
    print("已关闭图片识别。重启 AstrBot 生效。")
    return 0


def main():
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if action == "on":
        return cmd_on()
    if action == "off":
        return cmd_off()
    if action == "status":
        return cmd_status()
    print("用法: vision_setup.py [on|off|status]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
