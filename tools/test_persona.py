"""人设自测：跑一批固定场景，看她的回复像不像九条都。

改完 `persona/九条都-群聊人设.md` 后双击 `test-persona.bat`，
不用每次都去 QQ 群里试。

用法：
    local\\venv\\Scripts\\python.exe test_persona.py
    local\\venv\\Scripts\\python.exe test_persona.py --save   # 存一份带时间戳的结果
"""

import io
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级
PERSONA = os.path.join(ROOT, "persona", "九条都-群聊人设.md")
ENV = os.path.join(ROOT, ".env")

SCENARIOS = [
    ("日常", "今天食堂的菜好难吃"),
    ("小恶魔", "@都 你猜我刚才干了什么"),
    ("钱", "楼下新开了家日料，人均三百"),
    ("关系", "@都 希亚今天好冷淡啊"),
    ("正义感", "楼下便利店老板总多收学生钱，烦死了"),
    ("被逗", "@都 你是不是觉得我很菜"),
    ("关心", "今天加班到十点，人都傻了"),
    ("不懂装懂", "@都 python 的装饰器怎么理解"),
    ("素材", "@都 你平时除了打工还干嘛"),
    ("收尾", "晚安，睡了"),
]


def read_key():
    with io.open(ENV, encoding="utf-8") as f:
        for line in f:
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def chat(key, system_prompt, message):
    body = {
        "model": "deepseek-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "max_tokens": 220,
        "thinking": {"type": "disabled"},
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"].strip(), time.time() - t0


def _has_kana(text):
    return any("\u3040" <= c <= "\u30ff" for c in text)


def check(text):
    """几个能自动判的指标，帮你快速发现退化。日语和中文分开判。"""
    flags = []
    ja = _has_kana(text)
    limit = 70 if ja else 45
    if len(text) > limit:
        flags.append(f"超长{len(text)}字")
    if text.count("对不起") > 1:
        flags.append(f"道歉{text.count('对不起')}次")
    stripped = text.strip()
    if stripped.endswith(("？", "?")) and len(stripped) < 16:
        flags.append("只有反问")
    service_words = ("有什么可以帮你的", "希望对你有帮助", "我理解你的感受", "建议你可以")
    if ja:
        service_words = ("お役に立てれば", "何かお手伝いできること", "お気持ちは分かりま",
                         "ご提案ですが", "ご参考になれば")
    for word in service_words:
        if word in text:
            flags.append("客服腔"); break
    empty_words = ("没什么", "就那样", "也就那样") if not ja else ("別に", "特に何も", "なんでもない")
    for word in empty_words:
        if word in text and len(text) < 40:
            flags.append("空回答"); break
    return flags


def main():
    key = read_key()
    if not key:
        print("[ERROR] .env 里没有 DEEPSEEK_API_KEY")
        return 1
    if not os.path.exists(PERSONA):
        print(f"[ERROR] 找不到 {PERSONA}")
        return 1

    persona = io.open(PERSONA, encoding="utf-8").read().strip()
    print("=" * 66)
    print(f" 人设自测    {len(persona)} 字 ≈ {int(len(persona) * 0.7)} tokens")
    print("=" * 66)

    lines = []
    warn_count = 0
    total_time = 0.0

    for i, (tag, msg) in enumerate(SCENARIOS, 1):
        try:
            reply, dt = chat(key, persona, msg)
        except Exception as e:
            reply, dt = f"<失败: {type(e).__name__}: {e}>", 0.0
        total_time += dt
        flags = check(reply)
        if flags:
            warn_count += len(flags)

        head = f"{i:2d}. [{tag}] {msg}"
        print(f"\n{head}")
        print(f"    {reply}")
        info = f"    {len(reply)}字 / {dt:.1f}s"
        if flags:
            info += "  ⚠ " + "、".join(flags)
        print(info)

        lines.append(head)
        lines.append(f"    {reply}")
        lines.append(info)
        lines.append("")
        time.sleep(0.7)

    print("\n" + "=" * 66)
    print(f" 平均 {total_time / len(SCENARIOS):.1f}s / 条，异常标记 {warn_count} 处")
    print("=" * 66)

    if "--save" in sys.argv:
        out = os.path.join(
            ROOT, "persona-test-" + time.strftime("%m%d-%H%M") + ".txt"
        )
        io.open(out, "w", encoding="utf-8").write("\n".join(lines))
        print(f"结果已保存：{out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
