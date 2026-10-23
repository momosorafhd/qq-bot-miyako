"""结束占用 6185 端口的 AstrBot 进程（不管它有没有窗口）。

背景：AstrBot 的控制台窗口被关掉后，Python 进程常常还在后台跑，
任务栏看不到、也点不掉，下次启动就会报 "Cannot acquire lock file"。
这个脚本按端口找到它并结束，省得开任务管理器。
"""

import os
import re
import subprocess
import sys

PORTS = (6185, 6199)


def find_pids():
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, encoding="gbk", errors="ignore"
        ).stdout
    except Exception as e:
        print(f"[ERROR] 跑 netstat 失败: {e}")
        return set()

    pids = set()
    for line in out.splitlines():
        if "LISTENING" not in line:
            continue
        for port in PORTS:
            if re.search(rf":{port}\s", line):
                parts = line.split()
                if parts and parts[-1].isdigit():
                    pids.add(parts[-1])
    return pids


def main():
    pids = find_pids()
    if not pids:
        print("没有发现正在运行的 AstrBot（6185/6199 都没被占用）。")
        return 0

    print(f"发现 AstrBot 进程: {', '.join(sorted(pids))}")
    for pid in pids:
        r = subprocess.run(
            ["taskkill", "/PID", pid, "/F"], capture_output=True, text=True, encoding="gbk", errors="ignore"
        )
        if r.returncode == 0:
            print(f"  已结束 PID {pid}")
        else:
            print(f"  结束 PID {pid} 失败: {(r.stdout or r.stderr).strip()[:120]}")

    print("\n现在可以双击 start-astrbot.bat 重新启动了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
