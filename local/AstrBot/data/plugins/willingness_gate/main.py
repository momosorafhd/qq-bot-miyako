"""发言意愿评估：把"固定概率插话"换成"先判断值不值得接话"。

流程：被点名（九条都/小都/都酱…）直接必接；其余消息按 CANDIDATE_RATE
抽样，用一次便宜的 LLM 调用打分 0-10，分够高（SCORE_THRESHOLD）才通过
官方 event.request_llm() 开口。开口后 COOLDOWN 秒内不再评估。

决策日志：每次进入评估的候选和最终结论都记到 data/decisions.jsonl
（自动裁到 LOG_MAX 行）。攒几天真实数据后按"该回应却沉默 / 无须回应
却插话"两类样本复盘，再回头调 CANDIDATE_RATE 和 SCORE_THRESHOLD。
"""

import json
import os
import random
import re
import time
import uuid
from collections import deque

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.platform import MessageType

# ---------------- 可调参数 ----------------
CANDIDATE_RATE = 0.5     # 多大比例的非唤醒消息进入 LLM 评估（成本闸门）
SCORE_THRESHOLD = 5      # 0-10，>= 这个数才开口（实测群聊闲聊多在 4-6 分）
COOLDOWN = 60            # 主动开口后的冷却（秒）
WINDOW = 18              # 给评分模型看的近期群聊行数
LINE_MAX = 80            # 单行消息截断长度
LOG_MAX = 1000           # 决策日志最多保留行数
NICKNAMES = ("九条都", "都酱", "小都", "都宝", "都都", "都妈", "都宝子")
# ------------------------------------------

SCORE_PROMPT = """你在评估：QQ群里的虚拟角色「九条都」（傲娇小恶魔系女高中生，说话短、带刺但可爱，不是客服）要不要主动接下面这句话。

最近的群聊记录（最后一行是候选消息）：
{window}

请只输出一个 0-10 的整数，表示她接话的价值：
- 0-3：别接（跟她完全无关、两个人正在连贯私聊、她刚说过话、接了很突兀）
- 4-6：普通闲聊——聊到吃的东西、吐槽、玩梗、提到日常话题，她完全可以插一句
- 7-10：明显值得接（有人点名她、有趣、能吐槽、群里冷场、提到她的设定）
只输出数字，不要解释。"""


def _score_of(text: str) -> int:
    m = re.search(r"\b(10|[0-9])\b", text or "")
    return int(m.group(1)) if m else -1


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        self._dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(self._dir, exist_ok=True)
        self._log_path = os.path.join(self._dir, "decisions.jsonl")
        self._lines: dict[str, deque] = {}      # umo -> 最近群聊行
        self._last_speak: dict[str, float] = {} # umo -> 上次主动开口时间
        logger.info(
            f"[will] 意愿评估已生效：抽样 {int(CANDIDATE_RATE * 100)}%，"
            f"阈值 {SCORE_THRESHOLD}，冷却 {COOLDOWN}s",
        )

    # ---------------- 决策日志 ----------------

    def _log(self, umo: str, text: str, score: int, verdict: str) -> None:
        try:
            lines = []
            if os.path.exists(self._log_path):
                with open(self._log_path, encoding="utf-8") as f:
                    lines = f.readlines()
            if len(lines) >= LOG_MAX:
                lines = lines[-LOG_MAX // 2:]
                with open(self._log_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            rec = {
                "t": time.strftime("%m-%d %H:%M:%S"),
                "group": umo.split(":")[-1][:12],
                "text": text[:40],
                "score": score,
                "verdict": verdict,
            }
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"[will] 日志写入失败: {e}")

    # ---------------- 主管道 ----------------

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL, priority=-1)
    async def gate(self, event: AstrMessageEvent):
        if event.get_message_type() != MessageType.GROUP_MESSAGE:
            return
        if event.is_at_or_wake_command:
            return  # @/唤醒前缀：内核自己会处理，不归我们管
        text = (event.message_str or "").strip()
        if not text:
            return

        umo = event.unified_msg_origin

        # 1) 记录到滚动窗口（评分用）
        line = f"{event.get_sender_name()}[{time.strftime('%H:%M')}]: {text[:LINE_MAX]}"
        buf = self._lines.setdefault(umo, deque(maxlen=WINDOW))
        buf.append(line)

        # 2) 冷却期内只潜水
        now = time.time()
        if now - self._last_speak.get(umo, 0.0) < COOLDOWN:
            return

        # 3) 被点名直接满分；否则抽样决定要不要花一次评分调用
        if not any(nick in text for nick in NICKNAMES):
            if random.random() >= CANDIDATE_RATE:
                return

        score = await self._evaluate(umo, text)
        verdict = "speak" if score >= SCORE_THRESHOLD else f"low-score({score})"
        self._log(umo, text, score, verdict)
        if score < SCORE_THRESHOLD:
            return

        # 4) 开口：走和内核主动回复完全相同的链路
        try:
            cid = await self.context.conversation_manager.get_curr_conversation_id(umo)
            if not cid:
                logger.error("[will] 无活动会话，无法主动回复")
                return
            conv = await self.context.conversation_manager.get_conversation(umo, cid)
            if not conv:
                return
        except Exception as e:
            logger.error(f"[will] 取会话失败: {e}")
            return

        self._last_speak[umo] = now
        yield event.request_llm(
            prompt=text,
            session_id=event.session_id,
            conversation=conv,
        )

    async def _evaluate(self, umo: str, text: str) -> int:
        if any(nick in text for nick in NICKNAMES):
            return 10
        try:
            provider = await self.context.get_using_provider_async(umo)
            if not provider:
                return -1
            window = "\n".join(self._lines.get(umo, deque()))
            resp = await provider.text_chat(
                prompt=SCORE_PROMPT.format(window=window),
                session_id=uuid.uuid4().hex,
                contexts=[],
                persist=False,
            )
            return _score_of(resp.completion_text)
        except Exception as e:
            logger.error(f"[will] 评估失败，本次放弃: {e}")
            return -1
