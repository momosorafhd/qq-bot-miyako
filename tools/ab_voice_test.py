"""GPT-SoVITS 权重对比测试：同一批句子在不同权重下各合成一遍。

用法：python ab_voice_test.py
前置：9880 已启动（tools\\start-gsv.bat）。测试完自动把权重切回「自己版」。
产物：voice/ab_test/<配置>_<句号>.wav，另打印每句耗时。
"""

import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request

GSV = "http://127.0.0.1:9880"
OUT = r"E:\氛围传输素材\qq-bot\voice\ab_test"
REF_WAV = r"E:\氛围传输素材\qq-bot\voice\ref\normal.wav"
REF_TXT = (
    io.open(r"E:\氛围传输素材\qq-bot\voice\ref\normal.txt", encoding="utf-8")
    .read()
    .strip()
)
F = r"F:\GPT-SoVITS-v2pro-20250604"

CONFIGS = [
    ("A_mine_e20", f"{F}\\GPT_weights_v2ProPlus\\miyako-e20.ckpt",
     f"{F}\\SoVITS_weights_v2ProPlus\\miyako_e20_s6840.pth"),
    ("B_11g_e20", f"{F}\\GPT_weights_v2ProPlus\\十一组GPT_weights_v2ProPlus\\miyako-e20.ckpt",
     f"{F}\\SoVITS_weights_v2ProPlus\\十一组SoVITS_weights_v2ProPlus\\miyako_e20_s1740.pth"),
    ("C_11g_e25", f"{F}\\GPT_weights_v2ProPlus\\十一组GPT_weights_v2ProPlus\\miyako-e20.ckpt",
     f"{F}\\SoVITS_weights_v2ProPlus\\十一组SoVITS_weights_v2ProPlus\\miyako_e25_s2175.pth"),
]

SENTENCES = [
    "あはは、なにそれ。ちょっと面白いね。",
    "うん、わかった。明日ね、ちゃんと教えて。",
    "えっと……それは、ちょっと、ひみつ。",
]

# 强制直连，不吃系统代理
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url: str, timeout: float = 90.0):
    req = urllib.request.Request(url, headers={"User-Agent": "ab-test"})
    return OPENER.open(req, timeout=timeout)


def swap(kind: str, path: str) -> None:
    q = urllib.parse.urlencode({"weights_path": path})
    url = f"{GSV}/set_{kind}_weights?{q}"
    try:
        with _get(url, timeout=60) as r:
            body = r.read().decode("utf-8", "ignore")
        print(f"    set_{kind}_weights -> {os.path.basename(path)} [{body[:40]}]")
    except Exception as e:
        print(f"    [X] 切换 {kind} 失败: {e}")
        raise


def synth(label: str, idx: int, text: str) -> float:
    params = {
        "text": text,
        "text_lang": "ja",
        "ref_audio_path": REF_WAV,
        "prompt_text": REF_TXT,
        "prompt_lang": "ja",
        "speed_factor": "1.0",
        "media_type": "wav",
        "streaming_mode": "false",
    }
    url = f"{GSV}/tts?{urllib.parse.urlencode(params)}"
    t0 = time.time()
    with _get(url) as r:
        data = r.read()
    dt = time.time() - t0
    if len(data) < 2000:
        raise RuntimeError(f"返回太小({len(data)}B): {data[:120]!r}")
    out = os.path.join(OUT, f"{label}_{idx}.wav")
    with open(out, "wb") as f:
        f.write(data)
    return dt


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    results = {}
    for label, gpt, sov in CONFIGS:
        print(f"== {label}")
        try:
            swap("gpt", gpt)
            swap("sovits", sov)
        except Exception:
            return 1
        time.sleep(6)  # 等模型装载
        # 暖机一句（不保存）
        try:
            synth(label, 0, "暖机。")
            os.remove(os.path.join(OUT, f"{label}_0.wav"))
        except Exception as e:
            print(f"    [X] 暖机失败: {e}")
            return 1
        for i, text in enumerate(SENTENCES, 1):
            try:
                dt = synth(label, i, text)
                results[f"{label}_{i}"] = round(dt, 2)
                print(f"    句{i} {dt:.2f}s -> {label}_{i}.wav")
            except Exception as e:
                print(f"    [X] 句{i} 失败: {e}")
                results[f"{label}_{i}"] = None
    # 测完切回自己版，保证现状不被改变
    print("== 恢复 A_mine_e20 权重")
    swap("gpt", CONFIGS[0][1])
    swap("sovits", CONFIGS[0][2])
    (io.open(os.path.join(OUT, "results.json"), "w", encoding="utf-8")
     .write(json.dumps(results, ensure_ascii=False, indent=1)))
    print("完成，产物在", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
