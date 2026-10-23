"""让九条都能真的接住群里的表情包和图片。

两件事：

1. **只对必要的图片做描述**。AstrBot 在每条群消息进入时都会调看图模型，
   不管后面回不回，群里刷图时调用量很大，所以这里加过滤：
       @ 她 / 唤醒她          -> 全部图片都描述
       消息里只有图片          -> 视为表情包/贴图，描述
       图文混排但有表情包标记   -> 只认 sub_type=1，描述
       其他                    -> 跳过，只留占位符

2. **纯图消息也能被她"看见"并回应**。AstrBot 的主动插话通道传给模型的 prompt 是
   `event.message_str`，纯图时它是空的；图片只放在 image_urls 里，而 DeepSeek 是
   纯文本模型，图片会被丢掉。结果就是她对着空 prompt 瞎答。
   所以这里在决定插话时，先把图片描述写进 message_str，再放行。

实现是给 GroupChatContext 的方法套一层，不改 AstrBot 源码。
上游结构变了插件会自己失效并打日志，不会把机器人弄崩。
"""

import asyncio
import base64
import contextvars
import glob
import hashlib
import os
import random
import shutil
import subprocess
import tempfile
import time

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Plain, Video
from astrbot.core.agent.message import TextPart

try:
    from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext
except Exception as exc:  # pragma: no cover - 只在上游改结构时发生
    GroupChatContext = None
    _IMPORT_ERROR = exc

# 用 contextvar 而不是实例属性，避免多个群同时处理消息时互相覆盖
_ALLOW = contextvars.ContextVar("caption_filter_allow", default=False)

SKIP_PLACEHOLDER = "（图片）"

# 纯图消息额外给一次开口机会（正常文字消息仍走 AstrBot 原来的 5%）
IMAGE_REPLY_PROBABILITY = 0.5
# 同一个群两次"对图开口"的最小间隔，防止刷屏
IMAGE_REPLY_COOLDOWN = 60.0

_last_image_reply: dict[str, float] = {}
_caption_cache: dict[str, str] = {}
_CACHE_LIMIT = 300

_ORIG_CAPTION = None


def _has_sticker_marker(event: AstrMessageEvent) -> bool:
    """从 OneBot 原始事件里找 sub_type=1 的图片，那是 QQ 的动画表情。"""
    try:
        raw = getattr(event.message_obj, "raw_message", None)
        segments = raw.get("message") if isinstance(raw, dict) else getattr(raw, "message", None)
        if not isinstance(segments, list):
            return False
        for seg in segments:
            if not isinstance(seg, dict) or seg.get("type") != "image":
                continue
            data = seg.get("data") or {}
            if str(data.get("sub_type", "")) == "1":
                return True
            if "表情" in str(data.get("summary", "")):
                return True
    except Exception:
        pass
    return False


def _split(event: AstrMessageEvent):
    """返回 (图片组件列表, 有没有正文)。"""
    components = event.get_messages()
    images = [c for c in components if isinstance(c, Image)]
    has_text = any(isinstance(c, Plain) and c.text.strip() for c in components)
    return images, has_text


def _should_caption(event: AstrMessageEvent) -> bool:
    if event.is_at_or_wake_command:
        return True

    images, has_text = _split(event)
    if not images:
        return False
    if not has_text:
        # 只发了一张图，没有配文 —— 群聊里这基本就是表情包
        return True
    return _has_sticker_marker(event)


def _image_url(comp) -> str:
    return comp.url or comp.file or ""


# ---------- 视频：抽帧交给看图模型 ----------

VIDEO_FRAMES = 3
_FFMPEG_CACHE: str | None = None


def _ffmpeg_path() -> str | None:
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE:
        return _FFMPEG_CACHE
    candidates = [
        os.environ.get("FFMPEG_PATH", ""),
        "ffmpeg",
        r"D:\ImageMagick-7.0.10-Q16\ffmpeg.exe",
    ]
    for c in candidates:
        if not c:
            continue
        if os.path.isabs(c):
            if os.path.exists(c):
                _FFMPEG_CACHE = c
                return c
        else:
            found = shutil.which(c)
            if found:
                _FFMPEG_CACHE = found
                return found
    return None


def _grab_frames(video_path: str, outdir: str) -> list[str]:
    ff = _ffmpeg_path()
    if not ff:
        return []
    pattern = os.path.join(outdir, "f_%02d.jpg")
    cmd = [
        ff, "-y", "-loglevel", "error", "-i", video_path,
        "-vf", "fps=1/1.5", "-frames:v", str(VIDEO_FRAMES), pattern,
    ]
    try:
        subprocess.run(cmd, timeout=40, capture_output=True)
    except Exception as e:
        logger.error(f"[caption_filter] 抽帧失败: {e}")
        return []
    return sorted(glob.glob(os.path.join(outdir, "f_*.jpg")))


async def _describe_video(owner, comp, provider_id: str, prompt: str) -> str:
    """下载视频 → 抽 3 帧 → 逐帧描述 → 拼成一句。"""
    try:
        path = await comp.convert_to_file_path()
    except Exception as e:
        logger.error(f"[caption_filter] 取视频失败: {e}")
        return ""

    try:
        digest = hashlib.sha1(path.encode()).hexdigest()[:16]
    except Exception:
        digest = str(int(time.time()))
    if digest in _caption_cache:
        return _caption_cache[digest]

    tmpdir = tempfile.mkdtemp(prefix="vid_")
    try:
        frames = await asyncio.to_thread(_grab_frames, path, tmpdir)
        if not frames:
            return ""
        descs = []
        for fp in frames:
            try:
                b64 = base64.b64encode(open(fp, "rb").read()).decode()
            except Exception:
                continue
            try:
                d = await _ORIG_CAPTION(owner, b64, provider_id, prompt)
            except Exception as e:
                logger.error(f"[caption_filter] 帧描述失败: {e}")
                continue
            if d and d not in descs:
                descs.append(d)
        if not descs:
            return ""
        text = "；".join(descs)
        if len(_caption_cache) < _CACHE_LIMIT:
            _caption_cache[digest] = text
        return text
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _caption_cached(owner, url, provider_id, prompt):
    """带缓存的描述调用。同一张图（表情包常重复）不会重复花钱。"""
    if not url:
        return ""
    if url in _caption_cache:
        return _caption_cache[url]
    if _ORIG_CAPTION is None:
        return ""
    text = await _ORIG_CAPTION(owner, url, provider_id, prompt)
    if len(_caption_cache) < _CACHE_LIMIT:
        _caption_cache[url] = text
    return text


def _install() -> None:
    global _ORIG_CAPTION

    if GroupChatContext is None:
        logger.error(f"[caption_filter] 无法导入 GroupChatContext，插件未生效: {_IMPORT_ERROR}")
        return
    if getattr(GroupChatContext, "_caption_filter_patched", False):
        return

    orig_format = GroupChatContext._format_message
    orig_caption = GroupChatContext.get_image_caption
    orig_active = GroupChatContext.need_active_reply
    orig_req = GroupChatContext.on_req_llm
    _ORIG_CAPTION = orig_caption

    async def _format_message(self, event, cfg):
        try:
            allow = _should_caption(event)
        except Exception:
            allow = True  # 判断出错就退回"全都描述"，宁可多花钱也别失灵
        token = _ALLOW.set(allow)
        try:
            return await orig_format(self, event, cfg)
        finally:
            _ALLOW.reset(token)

    async def get_image_caption(self, image_url, provider_id, prompt):
        if not _ALLOW.get():
            return SKIP_PLACEHOLDER
        return await _caption_cached(self, image_url, provider_id, prompt)

    async def need_active_reply(self, event):
        # 原来的概率逻辑优先（文字消息仍然只按 possibility_reply 走）
        try:
            if await orig_active(self, event):
                return True
        except Exception:
            return False

        try:
            if event.is_at_or_wake_command:
                return False
            cfg = self.cfg(event)
            if not cfg["enable_active_reply"]:
                return False
            images, has_text = _split(event)
            if not images or has_text:
                return False

            umo = event.unified_msg_origin
            now = time.monotonic()
            if now - _last_image_reply.get(umo, -1e9) < IMAGE_REPLY_COOLDOWN:
                return False
            if random.random() >= IMAGE_REPLY_PROBABILITY:
                return False

            # 关键：把图的内容写进 prompt，否则模型收到的是空字符串
            caption = ""
            if cfg["image_caption"] and cfg["image_caption_provider_id"]:
                try:
                    caption = await _caption_cached(
                        self,
                        _image_url(images[0]),
                        cfg["image_caption_provider_id"],
                        cfg["image_caption_prompt"],
                    )
                except Exception as e:
                    logger.error(f"[caption_filter] 主动回复取图失败: {e}")

            event.message_str = (
                f"[群里发了一张图：{caption}]" if caption else "[群里发了一张图]"
            )
            _last_image_reply[umo] = now
            return True
        except Exception as e:
            logger.error(f"[caption_filter] 判断纯图插话失败: {e}")
            return False

    async def on_req_llm(self, event, req):
        """把「当前这条消息里的图」也告诉模型。

        AstrBot 的群聊上下文只注入当前消息**之前**的记录，所以 @ 她时一起发的图
        不在 prompt 里，她只看到文字，当然认不出是谁。
        """
        try:
            await orig_req(self, event, req)
        except Exception as e:
            logger.error(f"[caption_filter] 原 on_req_llm 出错: {e}")

        try:
            if (event.message_str or "").startswith("[群里发了一张图"):
                return  # 主动回复那条已经把描述写进 prompt 了
            cfg = self.cfg(event)
            if not cfg["image_caption"] or not cfg["image_caption_provider_id"]:
                return

            images, _ = _split(event)
            videos = [c for c in event.get_messages() if isinstance(c, Video)]

            # 视频只在「明确找她」时看，避免每条群视频都抽帧
            if videos and event.is_at_or_wake_command:
                desc = await _describe_video(
                    self,
                    videos[0],
                    cfg["image_caption_provider_id"],
                    cfg["image_caption_prompt"],
                )
                if desc:
                    req.extra_user_content_parts.append(
                        TextPart(text="[这条消息附带的视频：" + desc + "]")
                    )

            if not images:
                return
            if not _should_caption(event):
                return

            captions = []
            for comp in images[:2]:  # 一条消息最多看两张
                text = await _caption_cached(
                    self,
                    _image_url(comp),
                    cfg["image_caption_provider_id"],
                    cfg["image_caption_prompt"],
                )
                if text and text != SKIP_PLACEHOLDER:
                    captions.append(text)
            if captions:
                req.extra_user_content_parts.append(
                    TextPart(text="[这条消息附带的图：" + "；".join(captions) + "]")
                )
        except Exception as e:
            logger.error(f"[caption_filter] 注入当前图描述失败: {e}")

    GroupChatContext._format_message = _format_message
    GroupChatContext.get_image_caption = get_image_caption
    GroupChatContext.need_active_reply = need_active_reply
    GroupChatContext.on_req_llm = on_req_llm
    GroupChatContext._caption_filter_patched = True
    logger.info(
        "[caption_filter] 已生效：只描述表情包和 @ 的图；"
        f"纯图有 {int(IMAGE_REPLY_PROBABILITY * 100)}% 概率接一句（同群 {int(IMAGE_REPLY_COOLDOWN)}s 冷却）"
    )


_install()


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
