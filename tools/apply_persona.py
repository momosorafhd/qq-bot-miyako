"""把 persona/九条都-群聊人设.md 写进 AstrBot 的人格库。

AstrBot 的人格存在 data/data_v4.db 的 personas 表，不是读 md 文件。
改完 md 后跑这个脚本，人格才会更新；跑完要重启 AstrBot 才生效。

用法（双击 apply-persona.bat 即可）：
    local\\venv\\Scripts\\python.exe apply_persona.py
"""

import datetime
import io
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级
MD = os.path.join(ROOT, "persona", "九条都-群聊人设.md")
DB = os.path.join(ROOT, "local", "AstrBot", "data", "data_v4.db")
PERSONA_ID = "miyako"


def main():
    if not os.path.exists(MD):
        print(f"[ERROR] 找不到人设文件：{MD}")
        return 1
    if not os.path.exists(DB):
        print(f"[ERROR] 找不到数据库：{DB}")
        print("        先启动一次 AstrBot，让它把 data_v4.db 建出来。")
        return 1

    text = io.open(MD, encoding="utf-8").read().strip()
    if not text:
        print("[ERROR] 人设文件是空的。")
        return 1

    now = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(tzinfo=None)
        .strftime("%Y-%m-%d %H:%M:%S.%f")
    )

    shutil.copyfile(DB, DB + ".bak")

    c = sqlite3.connect(DB)
    row = c.execute(
        "select length(system_prompt) from personas where persona_id=?", (PERSONA_ID,)
    ).fetchone()

    if row:
        c.execute(
            "update personas set system_prompt=?, updated_at=? where persona_id=?",
            (text, now, PERSONA_ID),
        )
        action = f"更新（{row[0]} -> {len(text)} 字符）"
    else:
        c.execute(
            """insert into personas
               (created_at, updated_at, persona_id, system_prompt, begin_dialogs,
                tools, skills, custom_error_message, folder_id, sort_order)
               values (?,?,?,?,?,?,?,?,?,?)""",
            (now, now, PERSONA_ID, text, "[]", None, None, None, None, 1),
        )
        action = f"新建（{len(text)} 字符）"

    c.commit()
    c.close()

    print(f"人格 {PERSONA_ID} {action}")
    print(f"文件：{MD}")
    print()
    print("注意：AstrBot 只在启动时读一次人格。")
    print("      要生效，双击 start-astrbot.bat 重启，然后在群里发 /reset。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
