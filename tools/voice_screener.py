"""GPT-SoVITS 训练集筛选：先把明显不能用的挑出来。

它不做识别，只看声学指标，所以很快、离线、不花钱：

    python voice_screener.py D:\\dataset\\
    python voice_screener.py D:\\dataset\\ --move     # 分到 _keep/_check/_reject 三个子目录

判什么：

   时长      太短（<1.5s）没上下文，太长（>15s）本来该先切片
   削波      峰值贴顶，声音是破的
   太小声    底噪以上的音量不够
   SNR       说话段和停顿段的能量差。差值小 = 停顿里一直有东西 = 背景音乐或噪声
   静音占比  整段几乎没声音，或者几乎没停顿（像连续音）
   频谱平坦度 接近噪声
   采样率    低于 16k 会明显糊

注意：这是**启发式**，不是人耳。SNR 低只说明"停顿里不干净"，可能是音乐、
可能是空调声、也可能是房间混响——具体要自己听。所以只给三档：
keep / check / reject，check 那档建议抽听。

不会删除任何文件。--move 只是移动到子目录。
"""

import argparse
import csv
import os
import shutil
import sys

import numpy as np

try:
    import soundfile as sf
except ImportError:
    print("[ERROR] 缺 soundfile：local\\venv\\Scripts\\python.exe -m pip install soundfile")
    raise SystemExit(1)

AUDIO_EXT = (".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aif", ".aiff")

# 阈值集中在这里，按你的素材调整
MIN_DUR = 1.5
OK_DUR = (2.5, 10.0)
MAX_DUR = 15.0
CLIP_REJECT = 0.002
CLIP_WARN = 0.0005
RMS_MIN = -45.0
SNR_REJECT = 12.0
SNR_WARN = 20.0
SILENCE_MAX = 0.80
SILENCE_MIN = 0.04
FLATNESS_WARN = 0.25


def analyze(path: str) -> dict | None:
    try:
        data, sr = sf.read(path, always_2d=True)
    except Exception as e:
        return {"error": str(e)[:60]}

    if data.size == 0:
        return {"error": "空文件"}

    mono = data.mean(axis=1).astype(np.float64)
    dur = len(mono) / sr
    peak = float(np.max(np.abs(mono)))
    clip_ratio = float(np.mean(np.abs(mono) > 0.999))
    rms = float(np.sqrt(np.mean(mono**2)))
    rms_db = 20 * np.log10(rms + 1e-12)

    # 20ms 一帧算能量
    frame = max(1, int(0.02 * sr))
    n = len(mono) // frame
    if n >= 3:
        fr = mono[: n * frame].reshape(n, frame)
        fe = np.sqrt(np.mean(fr**2, axis=1)) + 1e-12
        db = 20 * np.log10(fe)
        p10, p90 = np.percentile(db, [10, 90])
        silence_ratio = float(np.mean(db < p90 - 35))
        snr = float(p90 - p10)
    else:
        silence_ratio, snr = 0.0, 0.0

    # 频谱平坦度（取中间一段 1 秒）
    start = max(0, len(mono) // 2 - sr // 2)
    seg = mono[start : start + sr]
    if len(seg) > 256:
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        spec = spec[spec > 1e-9]
        flatness = float(np.exp(np.mean(np.log(spec))) / (np.mean(spec) + 1e-12))
    else:
        flatness = 0.0

    return {
        "dur": dur,
        "sr": sr,
        "channels": data.shape[1],
        "peak_db": 20 * np.log10(peak + 1e-12),
        "rms_db": rms_db,
        "clip": clip_ratio,
        "snr": snr,
        "silence": silence_ratio,
        "flatness": flatness,
    }


def judge(m: dict) -> tuple[str, list[str], int]:
    """返回 (档位, 原因列表, 分数 0-100)。"""
    reasons = []
    score = 100

    dur = m["dur"]
    if dur < MIN_DUR:
        return "reject", [f"太短 {dur:.1f}s"], 10
    if dur > MAX_DUR:
        reasons.append(f"太长 {dur:.0f}s（该先切片）")
        score -= 35
    elif not (OK_DUR[0] <= dur <= OK_DUR[1]):
        reasons.append(f"时长 {dur:.1f}s 不在 {OK_DUR[0]}~{OK_DUR[1]}s")
        score -= 8

    if m["clip"] > CLIP_REJECT:
        return "reject", [f"削波 {m['clip']*100:.1f}%"], 15
    elif m["clip"] > CLIP_WARN:
        reasons.append(f"轻微削波 {m['clip']*100:.2f}%")
        score -= 12

    if m["rms_db"] < RMS_MIN:
        return "reject", [f"太小声 {m['rms_db']:.0f}dB"], 20

    if m["snr"] < SNR_REJECT:
        return "reject", [f"底噪太高 SNR {m['snr']:.0f}dB（可能有音乐/空调声）"], 25
    elif m["snr"] < SNR_WARN:
        reasons.append(f"SNR 偏低 {m['snr']:.0f}dB")
        score -= 15

    if m["silence"] > SILENCE_MAX:
        return "reject", [f"静音占 {m['silence']*100:.0f}%"], 15
    if m["silence"] < SILENCE_MIN and dur > 8:
        reasons.append("几乎没停顿（可能是连续音）")
        score -= 10

    if m["flatness"] > FLATNESS_WARN:
        reasons.append(f"频谱太平 {m['flatness']:.2f}（接近噪声）")
        score -= 10

    if m["sr"] < 16000:
        reasons.append(f"采样率 {m['sr']} 偏低")
        score -= 10

    if m["channels"] > 1:
        reasons.append("立体声（会被下混）")
        score -= 2

    score = max(0, min(100, score))
    if score >= 75:
        return "keep", reasons, score
    return "check", reasons, score


def fmt(m: dict, verdict: str, reasons: list[str], score: int) -> str:
    tag = {"keep": "OK  ", "check": "看  ", "reject": "删  "}[verdict]
    base = (
        f"{tag} {score:3d}分 {m['dur']:5.1f}s SNR{m['snr']:4.0f} "
        f"静音{m['silence']*100:3.0f}% 峰值{m['peak_db']:5.1f}dB"
    )
    return base + ("  " + "; ".join(reasons) if reasons else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="放音频的目录")
    ap.add_argument("--move", action="store_true", help="按档位移动到 _keep/_check/_reject")
    ap.add_argument("--csv", default="", help="报告输出路径，默认写到目录下 report.csv")
    ap.add_argument("--quiet", action="store_true", help="只打印汇总")
    args = ap.parse_args()

    root = os.path.abspath(args.folder)
    if not os.path.isdir(root):
        print(f"[ERROR] 不是目录：{root}")
        return 1

    files = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if os.path.isfile(p) and name.lower().endswith(AUDIO_EXT):
            files.append(p)

    if not files:
        print(f"[!] {root} 里没有音频文件（支持 {'/'.join(AUDIO_EXT)}）")
        return 0

    print("=" * 78)
    print(f" 扫描 {len(files)} 个文件：{root}")
    print("=" * 78)

    rows = []
    stats = {"keep": 0, "check": 0, "reject": 0}
    errors = 0

    for path in files:
        m = analyze(path)
        name = os.path.basename(path)
        if not m or "error" in m:
            errors += 1
            if not args.quiet:
                print(f"ERR  ???  {name}  ({m.get('error', '读不了') if m else '读不了'})")
            rows.append([name, "", "", "", "", "", "", "", "", "error", m.get("error", "") if m else ""])
            continue

        verdict, reasons, score = judge(m)
        stats[verdict] += 1
        if not args.quiet:
            print(fmt(m, verdict, reasons, score) + f"  {name}")
        rows.append([
            name, f"{m['dur']:.2f}", m["sr"], m["channels"],
            f"{m['peak_db']:.1f}", f"{m['rms_db']:.1f}",
            f"{m['clip']*100:.3f}", f"{m['snr']:.1f}",
            f"{m['silence']*100:.1f}", verdict, "; ".join(reasons),
        ])

    out_csv = args.csv or os.path.join(root, "report.csv")
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["文件", "时长s", "采样率", "声道", "峰值dB", "RMS dB",
                    "削波%", "SNR dB", "静音%", "判定", "原因"])
        w.writerows(rows)

    print("=" * 78)
    print(f" keep {stats['keep']} / check {stats['check']} / reject {stats['reject']}"
          + (f" / 读不了 {errors}" if errors else ""))
    print(f" 报告：{out_csv}")

    if args.move:
        for folder in ("_keep", "_check", "_reject"):
            os.makedirs(os.path.join(root, folder), exist_ok=True)
        moved = 0
        for row in rows:
            if len(row) < 10 or row[9] not in ("keep", "check", "reject"):
                continue
            src = os.path.join(root, row[0])
            dst = os.path.join(root, "_" + row[9], row[0])
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.move(src, dst)
                moved += 1
        print(f" 已移动 {moved} 个文件到 _keep/_check/_reject（没有删除任何东西）")

    print()
    print("建议：`看` 那一档抽听 5~10 条再决定；`删` 的里面如果听到人声正常的，")
    print("      多半是 SNR 阈值太严，改脚本顶部的 SNR_REJECT 再跑。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
