"""GPT-SoVITS 联通性自检：确认 9880 服务能不能出声音。

训练完模型、跑起 api_v2.py 之后，先跑这个，别等接进 AstrBot 才发现报错。

用法：
    local\\venv\\Scripts\\python.exe tts_probe.py
    local\\venv\\Scripts\\python.exe tts_probe.py --url http://127.0.0.1:9880 --ref 参考音频.wav --text "测试文本"
"""

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级
ENV = os.path.join(ROOT, ".env")
OUT = os.path.join(ROOT, "tts-test.wav")


def env_get(name: str, default: str = "") -> str:
    if not os.path.exists(ENV):
        return default
    with io.open(ENV, encoding="utf-8") as f:
        for line in f:
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return default


def _opener():
    """强制直连：本机服务不能走系统代理，否则会拿到代理返回的 502。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(alive_only: bool, url: str, ref: str, text: str) -> int:
    print(f"检查服务：{url}")
    op = _opener()
    try:
        with op.open(url.rstrip("/") + "/docs", timeout=8) as r:
            print(f"  服务在跑（HTTP {r.status}）")
    except urllib.error.HTTPError as e:
        if e.code in (502, 503, 504):
            print(f"  [X] 端口不通或服务没起来（HTTP {e.code}）")
            print("      检查：GPT-SoVITS 的 api_v2.py 是否运行、端口是否 9880。")
            return 1
        print(f"  端口通，但 /docs 返回 HTTP {e.code}（可能不是 GSV，也可能版本不同）")
    except Exception as e:
        print(f"  [X] 连不上：{type(e).__name__} {e}")
        print("      检查：GPT-SoVITS 的 api_v2.py 是否运行、端口是否 9880。")
        return 1

    if alive_only:
        return 0

    if not ref:
        print("\n[!] 没有参考音频（--ref 或 .env 里的 GSV_REF_AUDIO），跳过合成测试。")
        return 0

    payload = {
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": ref,
        "prompt_lang": "zh",
        "prompt_text": "",
        "media_type": "wav",
        "streaming_mode": False,
    }
    print(f"\n请求合成：{text}")
    req = urllib.request.Request(
        url.rstrip("/") + "/tts",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with _opener().open(req, timeout=90) as r:
            data = r.read()
        if len(data) < 1000:
            print(f"  [X] 返回内容太小（{len(data)} 字节），可能报错了：")
            print("      " + data[:300].decode("utf-8", "ignore"))
            return 1
        with open(OUT, "wb") as f:
            f.write(data)
        print(f"  [OK] 已生成 {OUT}（{len(data) // 1024} KB），播一下听听。")
        return 0
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode("utf-8", "ignore")
        print(f"  [X] HTTP {e.code}：{body}")
        print("      常见原因：ref_audio_path 路径不对、权重没加载、prompt_text 与参考音频不匹配。")
        return 1
    except Exception as e:
        print(f"  [X] {type(e).__name__}: {e}")
        return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=env_get("GSV_API_BASE", "http://127.0.0.1:9880"))
    ap.add_argument("--ref", default=env_get("GSV_REF_AUDIO", ""))
    ap.add_argument("--text", default="那个……晚饭有吃吗？我做了便当，要不要一起。")
    ap.add_argument("--alive", action="store_true", help="只检查服务在不在，不合成")
    args = ap.parse_args()
    return probe(args.alive, args.url, args.ref, args.text)


if __name__ == "__main__":
    sys.exit(main())
