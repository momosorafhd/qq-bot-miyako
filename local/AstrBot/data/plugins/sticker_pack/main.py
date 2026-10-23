"""表情包库：看群里谁发得多，收他的图，聊天时自己发。

规则（按你的意思改过）：

1. **先看人**：统计每个群友发了多少表情包，满 `STORE_MIN_SENDER` 张才开始收他的。
   发得少的人随手一张不占库位，发得多的才是"供货商"。
2. **收**：只收表情包（纯图消息，或带 QQ 表情标记的图），按 sha1 去重。
3. **淘汰**：库里满了就随机丢掉一成，不挑谁先来后到。

只收图不改消息，只发图不抢话。库在 pool/，可以随时手动删。
"""

import asyncio
import hashlib
import json
import os
import random
import time

import aiohttp

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain

# ---- 可调参数 ----
SEND_PROBABILITY = 0.08      # 普通回复后附一张的概率
MAX_STICKERS = 300           # 库容量上限
STORE_MIN_SENDER = 3         # 一个群友发够几张，才开始收他的
EVICT_RATIO = 0.1            # 满了以后一次丢掉的比例
MAX_REPLY_LEN = 70           # 回复太长就不附图，避免图文不搭
MIN_INTERVAL = 25.0          # 同群两次自动附图的最小间隔（秒）

ASK_WORDS = ("表情包", "来个表情", "发个表情", "来个图", "斗图")

ROOT = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.join(ROOT, "pool")
INDEX = os.path.join(ROOT, "index.json")


def _load() -> dict:
    if not os.path.exists(INDEX):
        return {"version": 1, "items": [], "senders": {}}
    try:
        with open(INDEX, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", [])
        data.setdefault("senders", {})
        return data
    except Exception:
        return {"version": 1, "items": [], "senders": {}}


def _save(data: dict) -> None:
    tmp = INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, INDEX)


def _evict(items: list[dict]) -> None:
    """满了随机丢一批。"""
    k = max(1, int(len(items) * EVICT_RATIO))
    for victim in random.sample(items, min(k, len(items))):
        try:
            os.remove(os.path.join(POOL, victim["file"]))
        except OSError:
            pass
        items.remove(victim)


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        os.makedirs(POOL, exist_ok=True)
        self._lock = asyncio.Lock()
        self._last_send: dict[str, float] = {}
        data = _load()
        logger.info(
            f"[sticker] 表情包库就绪：{len(data['items'])} 张，"
            f"{len(data['senders'])} 个群友发过图"
        )

    # ---------- 收 ----------
    def _is_sticker(self, event: AstrMessageEvent, has_text: bool) -> bool:
        if not has_text:
            return True
        try:
            raw = getattr(event.message_obj, "raw_message", None)
            segs = raw.get("message") if isinstance(raw, dict) else getattr(raw, "message", None)
            for seg in segs or []:
                if isinstance(seg, dict) and seg.get("type") == "image":
                    d = seg.get("data") or {}
                    if str(d.get("sub_type", "")) == "1":
                        return True
                    if "表情" in str(d.get("summary", "")):
                        return True
        except Exception:
            pass
        return False

    def _sniff(self, data: bytes, ctype: str = "") -> str | None:
        """看文件头认格式，返回扩展名。认不出就是 None。"""
        if not data or len(data) > 4 * 1024 * 1024:
            return None
        if data[:8].startswith(b"\x89PNG"):
            return ".png"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return ".gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return ".webp"
        if data[:3] == b"\xff\xd8\xff":
            return ".jpg"
        if "image" in (ctype or ""):
            return ".png"
        return None

    async def _fetch(self, comp) -> tuple[bytes, str] | None:
        """优先用 AstrBot 自己的解析器，它认得 QQ 的各种图片来源。

        直接拿 comp.url 走 HTTP 经常失败：QQ 的图有时候只在 file 里、
        有时候是 base64、有时候 URL 带鉴权。convert_to_file_path() 都处理了。
        """
        # 1) AstrBot 的解析器
        try:
            path = await comp.convert_to_file_path()
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()
                ext = self._sniff(data, "") or os.path.splitext(path)[1].lower() or ".jpg"
                if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                    return data, ext
        except Exception as e:
            logger.debug(f"[sticker] 本地解析失败: {e}")

        # 2) 兜底：直接下 URL
        url = comp.url or comp.file or ""
        if not url.startswith("http"):
            logger.info(f"[sticker] 取不到图（url 不是 http，也没有本地文件）: {url[:40]}")
            return None
        try:
            timeout = aiohttp.ClientTimeout(total=12)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url) as r:
                    if r.status != 200:
                        logger.info(f"[sticker] 下载失败 HTTP {r.status}")
                        return None
                    data = await r.read()
                    ctype = r.headers.get("Content-Type", "").lower()
        except Exception as e:
            logger.info(f"[sticker] 下载异常: {type(e).__name__}: {e}")
            return None

        ext = self._sniff(data, ctype)
        if not ext:
            logger.info(f"[sticker] 下回来的不是图片（{len(data)} 字节, {ctype}）")
            return None
        return data, ext

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def collect(self, event: AstrMessageEvent) -> None:
        comps = event.get_messages()
        images = [c for c in comps if isinstance(c, Image)]
        if not images:
            return
        has_text = any(isinstance(c, Plain) and c.text.strip() for c in comps)
        if not self._is_sticker(event, has_text):
            return

        sender_id = str(event.get_sender_id() or "")
        sender_name = event.get_sender_name() or sender_id

        # 1) 先记账：这个人发了几张
        async with self._lock:
            data = _load()
            st = data["senders"].setdefault(sender_id, {"name": sender_name, "count": 0})
            st["count"] += 1
            st["name"] = sender_name
            _save(data)
            count = st["count"]

        if count < STORE_MIN_SENDER:
            logger.debug(f"[sticker] {sender_name} 第 {count} 张，还没到收藏线")
            return

        if count == STORE_MIN_SENDER:
            logger.info(f"[sticker] {sender_name} 发够 {count} 张了，开始收他的表情包")

        # 2) 下载并入库
        for comp in images[:1]:
            got = await self._fetch(comp)
            if not got:
                continue
            body, ext = got
            digest = hashlib.sha1(body).hexdigest()[:16]

            async with self._lock:
                data = _load()
                items = data["items"]
                if any(it["hash"] == digest for it in items):
                    return
                if len(items) >= MAX_STICKERS:
                    _evict(items)
                name = digest + ext
                with open(os.path.join(POOL, name), "wb") as f:
                    f.write(body)
                items.append({
                    "hash": digest, "file": name, "used": 0,
                    "from": sender_name, "added": int(time.time()),
                })
                _save(data)
            logger.info(f"[sticker] 收下 {sender_name} 的表情包 {name}（共 {len(items)} 张）")
            return

    # ---------- 发 ----------
    def _pick(self, umo: str, want: bool) -> str | None:
        now = time.time()
        if not want:
            if now - self._last_send.get(umo, 0) < MIN_INTERVAL:
                return None
            if random.random() >= SEND_PROBABILITY:
                return None

        data = _load()
        items = [i for i in data["items"] if os.path.exists(os.path.join(POOL, i["file"]))]
        if not items:
            return None

        # 优先挑用得少的，避免老是同一张
        items.sort(key=lambda x: x.get("used", 0))
        head = items[: max(3, len(items) // 3)]
        chosen = random.choice(head)
        for it in data["items"]:
            if it["hash"] == chosen["hash"]:
                it["used"] = it.get("used", 0) + 1
                break
        _save(data)
        self._last_send[umo] = now
        return os.path.join(POOL, chosen["file"])

    @filter.on_decorating_result()
    async def attach(self, event: AstrMessageEvent) -> None:
        if not event.get_group_id():
            return
        result = event.get_result()
        if not result or not result.chain:
            return

        text = "".join(c.text for c in result.chain if isinstance(c, Plain))
        if len(text) > MAX_REPLY_LEN:
            return

        want = any(w in (event.message_str or "") for w in ASK_WORDS)
        path = self._pick(event.unified_msg_origin, want)
        if not path:
            return
        try:
            result.chain.append(Image.fromFileSystem(path))
        except Exception as e:
            logger.error(f"[sticker] 附表情包失败: {e}")
