"""设定速查：聊到剧情/设定/人物关系时，临时塞一张资料卡。

为什么不用知识库：AstrBot 的知识库要配 embedding 模型（要建库、切片、绑会话），
而她的设定总共就一千多字，塞一张卡片比向量检索更简单、更准，也不多花钱。

触发靠关键词，命中才注入；平时完全不占 prompt。
"""

import os

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.agent.message import TextPart

# 命中这些词就把卡片塞进去
KEYWORDS = (
    "设定", "剧情", "原作", "结局", "都线", "新章",
    "能力", "圣遗物", "异能", "魔眼", "石化", "神器",
    "希亚", "春风", "新海", "九条都",
    "动画", "第几部", "时间线", "人物关系",
)

CACHE = {"mtime": 0.0, "text": ""}


def _card_path() -> str | None:
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        cand = os.path.join(cur, "persona", "九条都-设定速查.md")
        if os.path.exists(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _load() -> str:
    p = _card_path()
    if not p:
        return ""
    try:
        mtime = os.path.getmtime(p)
        if mtime != CACHE["mtime"]:
            import io

            CACHE["text"] = io.open(p, encoding="utf-8").read().strip()
            CACHE["mtime"] = mtime
        return CACHE["text"]
    except Exception as e:
        logger.error(f"[kb_card] 读设定卡失败: {e}")
        return ""


def _hit(text: str) -> bool:
    return any(k in text for k in KEYWORDS)


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        card = _load()
        logger.info(f"[kb_card] 已生效，设定卡 {len(card)} 字，命中 {len(KEYWORDS)} 个关键词")

    @filter.on_llm_request()
    async def inject(self, event: AstrMessageEvent, req) -> None:
        msg = event.message_str or ""
        if not msg or not _hit(msg):
            return
        card = _load()
        if not card:
            return
        try:
            req.extra_user_content_parts.append(
                TextPart(
                    text="[设定资料，供你参考。不要照念，也不要承认自己在查资料]\n" + card
                ).mark_as_temp()
            )
            logger.info("[kb_card] 注入了设定卡")
        except Exception as e:
            logger.error(f"[kb_card] 注入失败: {e}")
