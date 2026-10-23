"""把训练好的 GPT-SoVITS 权重接进 AstrBot。

**文件放哪儿**：全部放在本项目的 `voice/` 目录下，脚本会自动扫：

    voice/weights/   xxx_e10_s100.pth（SoVITS）+ xxx-e15.ckpt（GPT）
    voice/ref/       miyako_ref.wav（3~10 秒参考音频）+ 可选 prompt.txt

用法：
    local\\venv\\Scripts\\python.exe tts_setup.py status
    local\\venv\\Scripts\\python.exe tts_setup.py on          # 自动扫 voice/
    local\\venv\\Scripts\\python.exe tts_setup.py on --sovits ... --gpt ... --ref ...
    local\\venv\\Scripts\\python.exe tts_setup.py off
"""

import argparse
import glob
import io
import json
import os
import shutil
import socket
import sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级
CFG = os.path.join(ROOT, "local", "AstrBot", "data", "cmd_config.json")
VOICE = os.path.join(ROOT, "voice")
WEIGHTS = os.path.join(VOICE, "weights")
REF = os.path.join(VOICE, "ref")
SRC_ID = "gsv_source"
PROVIDER_ID = "gsv-miyako"


def load_cfg():
    with io.open(CFG, encoding="utf-8-sig") as f:
        return json.load(f)


def save_cfg(d):
    shutil.copyfile(CFG, CFG + ".bak")
    with io.open(CFG, "w", encoding="utf-8-sig") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _find(folder, patterns):
    hits = []
    for pat in patterns:
        hits.extend(glob.glob(os.path.join(folder, "**", pat), recursive=True))
    return sorted({os.path.abspath(h) for h in hits}, key=os.path.getmtime, reverse=True)


def discover():
    """在 voice/ 下自动找权重和参考音频。多个同类型时取最新的那个。"""
    sovits = _find(WEIGHTS, ["*.pth"])
    gpt = _find(WEIGHTS, ["*.ckpt"])
    refs = _find(REF, ["*.wav", "*.mp3", "*.flac"])

    prompt_text = ""
    ptxt = os.path.join(REF, "prompt.txt")
    if os.path.exists(ptxt):
        prompt_text = io.open(ptxt, encoding="utf-8").read().strip()

    return sovits, gpt, refs, prompt_text


def port_open(api_base: str) -> bool:
    u = urlparse(api_base)
    host = u.hostname or "127.0.0.1"
    port = u.port or 9880
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def apply_mode(tts: dict, mode: str) -> str:
    """三种说话方式：
    voice = 每条都发语音，不发文字（最像在说话）
    both  = 每条都发语音 + 文字（能听也能读）
    rare  = 偶尔发语音，平时是文字
    """
    if mode == "voice":
        tts["trigger_probability"] = 1.0
        tts["dual_output"] = False
        return "每条回复都是语音"
    if mode == "half":
        tts["trigger_probability"] = 0.5
        tts["dual_output"] = True
        return "一半的回复是「日语语音 + 中文文字」，其余纯文字"
    if mode == "both":
        tts["trigger_probability"] = 1.0
        tts["dual_output"] = True
        return "每条回复都发语音 + 文字"
    tts["trigger_probability"] = 0.15
    tts["dual_output"] = True
    return "约七分之一的回复带语音"


def cmd_status():
    d = load_cfg()
    src = next((s for s in d["provider_sources"] if s.get("id") == SRC_ID), None)
    prov = next((p for p in d["provider"] if p.get("id") == PROVIDER_ID), None)
    tts = d.get("provider_tts_settings", {})
    sovits, gpt, refs, _ = discover()

    print("  --- 文件 ---")
    print(f"  voice/weights/   SoVITS {len(sovits)} 个, GPT {len(gpt)} 个")
    for p in sovits[:3]:
        print(f"      {os.path.basename(p)}")
    for p in gpt[:3]:
        print(f"      {os.path.basename(p)}")
    print(f"  voice/ref/       音频 {len(refs)} 个")
    for p in refs[:3]:
        print(f"      {os.path.basename(p)}")

    print("  --- 配置 ---")
    print(f"  TTS 总开关        : {tts.get('enable')}")
    print(f"  默认 TTS provider : {tts.get('provider_id') or '(空)'}")
    prob = tts.get("trigger_probability", 0)
    dual = tts.get("dual_output", False)
    if prob >= 0.99:
        desc = "每条回复都发语音" + ("＋文字" if dual else "（不发文字）")
    elif prob > 0:
        desc = f"约 1/{round(1 / prob)} 的回复带语音" + ("＋文字" if dual else "")
    else:
        desc = "从不发语音"
    print(f"  说话方式          : {desc}")
    print(f"  provider 已启用    : {bool(prov and prov.get('enable'))}")
    if src:
        print(f"  api_base          : {src.get('api_base')}")
        print(f"  已写入 SoVITS     : {os.path.basename(src.get('sovits_weights_path') or '(未设)')}")
        print(f"  已写入 GPT        : {os.path.basename(src.get('gpt_weights_path') or '(未设)')}")
        print(f"  9880 端口         : {'通' if port_open(src.get('api_base', 'http://127.0.0.1:9880')) else '不通（服务没起）'}")
    else:
        print("  provider          : 还没配置过")

    ok = (
        tts.get("enable")
        and tts.get("provider_id") == PROVIDER_ID
        and prov
        and prov.get("enable")
    )
    print()
    print("  结论:", "语音已接上" if ok else "语音未开启")
    return 0


def guess_lang(text: str) -> str:
    """从参考文本猜语言：有假名就是日语，纯汉字当中文。"""
    if any("\u3040" <= c <= "\u30ff" for c in text):
        return "ja"
    if any("\uac00" <= c <= "\ud7af" for c in text):
        return "ko"
    if any("\u4e00" <= c <= "\u9fff" for c in text):
        return "zh"
    return "en"


def cmd_on(args):
    sovits_list, gpt_list, ref_list, prompt_text = discover()

    sovits = args.sovits or (sovits_list[0] if sovits_list else "")
    gpt = args.gpt or (gpt_list[0] if gpt_list else "")
    ref = args.ref or (ref_list[0] if ref_list else "")
    ptxt = args.prompt_text or prompt_text

    for label, path in (("SoVITS 权重", sovits), ("GPT 权重", gpt), ("参考音频", ref)):
        if not path:
            print(f"[ERROR] 没找到{label}。")
            print(f"        放到 {WEIGHTS if '权重' in label else REF} 下面，或者用参数指定。")
            return 1
        if not os.path.exists(path):
            print(f"[ERROR] {label} 不存在：{path}")
            return 1
        if not os.path.isabs(path):
            print(f"[ERROR] {label} 要写绝对路径：{path}")
            return 1

    if len(sovits_list) > 1:
        print(f"[!] voice/weights 里有 {len(sovits_list)} 个 .pth，用了最新的：{os.path.basename(sovits)}")
    if len(gpt_list) > 1:
        print(f"[!] voice/weights 里有 {len(gpt_list)} 个 .ckpt，用了最新的：{os.path.basename(gpt)}")
    if len(ref_list) > 1:
        print(f"[!] voice/ref 里有 {len(ref_list)} 个音频，用了最新的：{os.path.basename(ref)}")

    if not port_open(args.api_base):
        print(f"[ERROR] {args.api_base} 连不上，先把 GPT-SoVITS 的 api_v2.py 跑起来。")
        print("        跑起来后可以用 tts-probe.bat 验证能不能出声。")
        return 1

    d = load_cfg()

    # 参考音频可能是日语（游戏语音），要说中文就得跨语言：
    # text_lang=zh 决定"合成什么语言"，prompt_lang 决定"参考音频是什么语言"
    if args.prompt_lang == "auto":
        prompt_lang = guess_lang(ptxt) if ptxt else args.text_lang
    else:
        prompt_lang = args.prompt_lang

    source = {
        "id": SRC_ID,
        "provider": "gpt_sovits",
        "type": "gsv_tts_selfhost",
        "provider_type": "text_to_speech",
        "api_base": args.api_base,
        "gpt_weights_path": gpt,
        "sovits_weights_path": sovits,
        "timeout": 90,
        "gsv_default_parms": {
            "gsv_text_lang": args.text_lang,
            "gsv_prompt_lang": prompt_lang,
            "gsv_ref_audio_path": ref,
            "gsv_prompt_text": ptxt,
            "gsv_media_type": "wav",
            "gsv_streaming_mode": "false",
            "gsv_top_k": "15",
            "gsv_top_p": "1",
            "gsv_temperature": "1",
            "gsv_speed_factor": args.speed,
        },
    }
    d["provider_sources"] = [s for s in d["provider_sources"] if s.get("id") != SRC_ID]
    d["provider_sources"].append(source)

    d["provider"] = [p for p in d["provider"] if p.get("id") != PROVIDER_ID]
    d["provider"].append({
        "id": PROVIDER_ID,
        "enable": True,
        "provider_source_id": SRC_ID,
    })

    tts = d.setdefault("provider_tts_settings", {})
    tts["enable"] = True
    tts["provider_id"] = PROVIDER_ID
    mode_desc = apply_mode(tts, args.mode)

    save_cfg(d)
    print("已接上 GPT-SoVITS：")
    print(f"  权重  {os.path.basename(sovits)} + {os.path.basename(gpt)}")
    print(f"  参考  {os.path.basename(ref)}" + ("（有 prompt.txt）" if ptxt else "（没写参考文本，GSV 会自己处理）"))
    print(f"  语言  合成 {args.text_lang} / 参考 {prompt_lang}" +
          ("（跨语言，听起来会带点日语口音，正常）" if prompt_lang != args.text_lang else ""))
    print(f"  方式  {mode_desc}")
    print()
    print("重启 AstrBot 生效。第一次先发一句短的，看群里有没有语音。")
    return 0


def cmd_lang(lang: str):
    """只改合成语言，不动权重路径，所以不需要 GSV 在线。"""
    d = load_cfg()
    src = next((s for s in d["provider_sources"] if s.get("id") == SRC_ID), None)
    if not src:
        print("[ERROR] 语音还没接线，先跑 `tts_setup.py on`。")
        return 1
    src.setdefault("gsv_default_parms", {})["gsv_text_lang"] = lang
    save_cfg(d)
    print(f"合成语言已改为 {lang}（参考音频语言不变）。重启 AstrBot 生效。")
    return 0


def cmd_mode(mode: str):
    """只切换说话方式，不改权重路径，所以不需要 GSV 在跑。"""
    d = load_cfg()
    tts = d.setdefault("provider_tts_settings", {})
    if not tts.get("provider_id"):
        print("[ERROR] 语音还没接线，先跑 `tts_setup.py on`。")
        return 1
    desc = apply_mode(tts, mode)
    save_cfg(d)
    print(f"已切换：{desc}")
    print("重启 AstrBot 生效。")
    return 0


def cmd_off():
    d = load_cfg()
    for p in d["provider"]:
        if p.get("id") == PROVIDER_ID:
            p["enable"] = False
    d.setdefault("provider_tts_settings", {})["enable"] = False
    save_cfg(d)
    print("已关闭语音。重启 AstrBot 生效。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["on", "off", "status", "mode", "lang"])
    ap.add_argument("value", nargs="?", default="",
                    help="mode 后面跟 voice/both/rare，如：tts_setup.py mode voice")
    ap.add_argument("--sovits", default="", help="不填则自动扫 voice/weights/*.pth")
    ap.add_argument("--gpt", default="", help="不填则自动扫 voice/weights/*.ckpt")
    ap.add_argument("--ref", default="", help="不填则自动扫 voice/ref/")
    ap.add_argument("--prompt-text", default="", help="不填则读 voice/ref/prompt.txt")
    ap.add_argument("--api-base", default="http://127.0.0.1:9880")
    ap.add_argument("--text-lang", default="zh", choices=["zh", "ja", "en", "auto"],
                    help="合成语言，默认中文")
    ap.add_argument("--prompt-lang", default="auto", choices=["zh", "ja", "en", "ko", "auto"],
                    help="参考音频的语言，auto 按 prompt.txt 里的文字判断")
    ap.add_argument("--speed", default="1.0", help="语速，0.9 会慢一点更贴她的语气")
    ap.add_argument("--mode", default="both", choices=["voice", "half", "both", "rare"],
                    help="voice=只说语音 / both=语音+文字 / rare=偶尔语音")
    args = ap.parse_args()

    if args.action == "mode":
        return cmd_mode(args.value or args.mode)
    if args.action == "lang":
        return cmd_lang(args.value or args.text_lang)
    if args.action == "on":
        return cmd_on(args)
    if args.action == "off":
        return cmd_off()
    return cmd_status()


if __name__ == "__main__":
    sys.exit(main())
