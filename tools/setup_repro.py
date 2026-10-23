"""一键复现：把仓库里的可复现配置 + 人设铺到本机。

做的事（幂等，可以重复跑）：
 1. 检查目录结构
 2. 没有 .env 就从 .env.example 生成，并提示填 key
 3. 没有 cmd_config.json 就用 cmd_config.repro.json 生成，
    把其中的 __PROJECT_ROOT__ 换成本机真实路径
 4. 已有配置修路径；仅对已知的无效change_me初始凭据备份后修复
 5. 人设写进数据库（需要先启动过一次 AstrBot，让它建库）
 6. 打印体检结果和下一步

用法：
    local\\venv\\Scripts\\python.exe tools\\setup_repro.py
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "local", "AstrBot", "data")
CFG = os.path.join(DATA, "cmd_config.json")
REPRO = os.path.join(DATA, "cmd_config.repro.json")
ENV = os.path.join(ROOT, ".env")
ENV_TPL = os.path.join(ROOT, ".env.example")
PY = os.path.join(ROOT, "local", "venv", "Scripts", "python.exe")


def ok(msg):
    print(f"  [OK]   {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def bad(msg):
    print(f"  [FAIL] {msg}")


def check_layout():
    print("[1/6] 目录检查")
    problems = 0
    for rel, label in [
        ("persona", "人设目录"),
        ("tools", "脚本目录"),
        (os.path.join("local", "AstrBot"), "AstrBot 本体"),
        (os.path.join("local", "venv"), "Python 虚拟环境"),
        (os.path.join("local", "NapCatShell"), "NapCat"),
    ]:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            ok(label)
        else:
            bad(f"{label} 缺失：{p}")
            problems += 1
    if not os.path.exists(os.path.join(ROOT, "local", "venv", "Scripts", "python.exe")):
        warn("没找到 venv 里的 python，后面需要手动装（见 REPRODUCE.md 第 2 步）")
    return problems


def setup_env():
    print("[2/6] API Key")
    if os.path.exists(ENV):
        txt = io.open(ENV, encoding="utf-8-sig").read()
        has = any(
            line.startswith("DEEPSEEK_API_KEY=") and len(line.split("=", 1)[1].strip()) > 10
            for line in txt.splitlines()
        )
        if has:
            ok(".env 已存在且填了 DeepSeek Key")
        else:
            warn(".env 存在但 DEEPSEEK_API_KEY 为空，去补上")
        return
    if not os.path.exists(ENV_TPL):
        warn("没有 .env.example，跳过")
        return
    io.open(ENV, "w", encoding="utf-8").write(io.open(ENV_TPL, encoding="utf-8-sig").read())
    warn("已从 .env.example 生成 .env —— 请打开它填 DEEPSEEK_API_KEY（和 ZHIPU_API_KEY）")


def patch_paths(cfg: dict) -> int:
    """把占位符换成本机路径；返回替换次数。"""
    n = 0

    def walk(o):
        nonlocal n
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and "__PROJECT_ROOT__" in v:
                    o[k] = v.replace("__PROJECT_ROOT__", ROOT)
                    n += 1
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(cfg)
    return n


def setup_config():
    print("[3/6] AstrBot 配置")
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(REPRO):
        bad("缺少 cmd_config.repro.json，无法复现调好的参数")
        return
    if not os.path.exists(CFG):
        with io.open(REPRO, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        n = patch_paths(cfg)
        write_config(cfg)
        ok(f"已从 repro 生成 cmd_config.json（替换 {n} 处路径）")
        warn("首次启动从AstrBot日志取得随机初始密码，并完成改密；管理员QQ/搜索key另行设置")
        return
    with io.open(CFG, encoding="utf-8-sig") as f:
        cfg = json.load(f)
    n = patch_paths(cfg)
    repaired = repair_bootstrap_auth(cfg)
    if repaired:
        backup = CFG + f".pre-bootstrap-fix-{time.time_ns()}.bak"
        shutil.copy2(CFG, backup)
        warn("已备份原配置并修复无效change_me凭据；下次启动从日志取得随机初始密码")
    if n or repaired:
        write_config(cfg)
        ok(f"已有配置，修好了 {n} 处路径" + ("及初始凭据" if repaired else ""))
    else:
        ok("已有配置，路径无需修改")


def write_config(cfg):
    fd, tmp = tempfile.mkstemp(dir=DATA, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CFG)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def repair_bootstrap_auth(cfg):
    """只识别上一版模板产生的无效组合；不重置任何有效密码/hash/JWT。"""
    dashboard = cfg.get("dashboard", {})
    if dashboard.get("password") != "change_me" or dashboard.get("pbkdf2_password"):
        return False
    dashboard.update(password="", password_storage_upgraded=False, password_change_required=True)
    return True


def setup_persona():
    print("[4/6] 人设入库")
    db = os.path.join(DATA, "data_v4.db")
    if not os.path.exists(db):
        warn("还没有 data_v4.db（先启动一次 AstrBot 让它建库，再重跑本脚本）")
        return
    script = os.path.join(ROOT, "tools", "apply_persona.py")
    if not os.path.exists(script):
        warn("缺少 apply_persona.py")
        return
    py = PY if os.path.exists(PY) else sys.executable
    r = subprocess.run([py, script], capture_output=True, text=True)
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    ok("人设已写入（" + (tail[-1] if tail else "完成") + "）") if r.returncode == 0 else warn(
        "人设写入失败：" + (tail[-1] if tail else str(r.returncode))
    )


def check_voice():
    print("[5/6] 语音素材")
    wdir = os.path.join(ROOT, "voice", "weights")
    ref = os.path.join(ROOT, "voice", "ref")
    ckpts = (
        [f for f in os.listdir(wdir) if f.endswith((".ckpt", ".pth"))]
        if os.path.isdir(wdir)
        else []
    )
    if len(ckpts) >= 2:
        ok(f"权重齐全（{len(ckpts)} 个文件）")
    else:
        warn("权重不全：从 GitHub Releases 下载 .ckpt + .pth 放进 voice/weights/")
    if os.path.isdir(ref) and any(f.endswith(".wav") for f in os.listdir(ref)):
        ok("参考音齐全（voice/ref）")
    else:
        warn("缺参考音")


def final_hint():
    print("[6/6] 下一步")
    print("  1) 启动 GPT-SoVITS：tools\\start-gsv.bat（等 Uvicorn running）")
    print("  2) 启动 AstrBot：  tools\\start-astrbot.bat")
    print("  3) 拉起 QQ/NapCat：tools\\launch-napcat.bat，扫码登录小号")
    print("  4) 体检：          tools\\doctor.bat  （应全绿）")
    print("  5) 群里发 /reset 开新会话，再 @她 试一句")


def main():
    print("=" * 50)
    print(" 九条都 bot · 一键复现")
    print("=" * 50)
    problems = check_layout()
    setup_env()
    setup_config()
    setup_persona()
    check_voice()
    final_hint()
    print()
    if problems:
        print(f"⚠ 有 {problems} 项目录缺失，先按 REPRODUCE.md 补齐再来。")
    else:
        print("目录结构完整。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
