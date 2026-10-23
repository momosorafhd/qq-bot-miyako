"""语音说日文，文字留中文。

问题：GPT-SoVITS 的模型是日语训练的，直接喂中文会读得很怪。
但群里又需要中文文字才能看懂。

做法：拦截 TTS 的合成调用，先把中文翻成日语口语，再交给 GPT-SoVITS。
文字部分不动——所以最终效果是「语音是日语，消息里能看到中文」。

还会按回复内容换参考音频（开心 / 害羞 / 低落），让语气跟着内容走。

不碰 AstrBot 源码，只包一层 ProviderGSVTTS.get_audio。
"""

import hashlib
import os

from astrbot.api import logger, star
from astrbot.core.provider.sources.gsv_selfhosted_source import ProviderGSVTTS

# 翻译用的系统提示词。要口语、要保住她那股"礼貌又犹豫"的语气。
PROMPT = """你是中文到日语的翻译。把用户发来的每一句中文，翻译成自然的日语口语。

规则：
- 只输出译文，不要解释、不要加引号、不要加原文。
- 用年轻女性的口语，语气软、略犹豫，可以保留"……"这种停顿。
- 不要过度敬语，不要书面语，不要"です・ます"连发。
- 专有名词（人名、店名）保留原样。
- 如果原文本身就是日语，原样返回。"""

_CTX = None
_ORIG = None
_CACHE: dict[str, str] = {}
_CACHE_MAX = 500

# ---- 情绪参考音频 ----
# 同一段参考音频会把语气复制到每一句上，所以按内容换参考音频。
# 文件都在 voice/ref/ 下：<名字>.wav + <名字>.txt（参考文本）
REF_DIR = None
EMO_RULES = {
    "happy": ("哈哈", "笑", "太好了", "开心", "嘿嘿", "好玩", "棒", "耶"),
    "shy": ("对不起", "不好意思", "抱歉", "害羞", "脸红", "唔", "那个"),
    "sad": ("难过", "累", "唉", "算了", "孤单", "想哭", "失落"),
}

# 光换参考音频，音高几乎不变（同一个人），主要靠语速拉出差别
EMO_SPEED = {"happy": "1.05", "shy": "0.93", "sad": "0.88"}
_REF_CACHE: dict[str, tuple[str, str]] = {}


def _init_ref_dir() -> None:
    """从插件位置往上找，直到看到 voice/ref 目录（不写死层级）。"""
    global REF_DIR
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        cand = os.path.join(cur, "voice", "ref")
        if os.path.isdir(cand):
            REF_DIR = cand
            return
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    logger.warning("[tts_ja] 没找到 voice/ref，情绪音频不会生效")


def _ref_for(emo: str) -> tuple[str, str] | None:
    """返回 (wav 路径, 参考文本)。文件不全就返回 None，退回默认参考音频。"""
    if emo in _REF_CACHE:
        return _REF_CACHE[emo]
    if not REF_DIR:
        return None
    import io

    wav = os.path.join(REF_DIR, f"{emo}.wav")
    txt = os.path.join(REF_DIR, f"{emo}.txt")
    if not os.path.exists(wav):
        return None
    prompt = ""
    if os.path.exists(txt):
        prompt = io.open(txt, encoding="utf-8").read().strip()
    _REF_CACHE[emo] = (wav, prompt)
    return wav, prompt


def _pick_emotion(text: str) -> str | None:
    """按关键词投票，票数最高且大于 0 才生效。"""
    best, best_score = None, 0
    for emo, words in EMO_RULES.items():
        score = sum(1 for w in words if w in text)
        if score > best_score:
            best, best_score = emo, score
    return best


def _has_kana(text: str) -> bool:
    return any("\u3040" <= c <= "\u30ff" for c in text)


def _clean(text: str) -> str:
    s = (text or "").strip()
    for pair in (("「", "」"), ("『", "』"), ('"', '"'), ("'", "'")):
        if s.startswith(pair[0]) and s.endswith(pair[1]) and len(s) > 2:
            s = s[1:-1].strip()
    return s.replace("\n", " ").strip()


async def _translate(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    if _has_kana(text):
        return text  # 已经是日语，不用翻

    key = hashlib.sha1(text.encode()).hexdigest()
    if key in _CACHE:
        return _CACHE[key]

    provider = None
    try:
        provider = _CTX.get_using_provider() if _CTX else None
    except Exception as e:
        logger.error(f"[tts_ja] 取聊天模型失败: {e}")
    if not provider:
        return text

    try:
        resp = await provider.text_chat(
            prompt=text, system_prompt=PROMPT, contexts=[]
        )
        ja = _clean(resp.completion_text)
    except Exception as e:
        logger.error(f"[tts_ja] 翻译失败，用原文合成: {e}")
        return text

    if not ja or not _has_kana(ja):
        logger.warning(f"[tts_ja] 翻译结果不像日语，用原文: {ja[:30]}")
        return text

    if len(_CACHE) < _CACHE_MAX:
        _CACHE[key] = ja
    logger.info(f"[tts_ja] {text[:24]} → {ja[:24]}")
    return ja


async def _get_audio(self, text: str) -> str:
    """替换 ProviderGSVTTS.get_audio：先挑情绪，再翻日语，最后合成。"""
    ja = await _translate(text)

    emo = _pick_emotion(text or "")
    ref = _ref_for(emo) if emo else None
    if not ref:
        return await _ORIG(self, ja)

    wav, prompt = ref
    params = getattr(self, "default_params", None)
    if not isinstance(params, dict):
        return await _ORIG(self, ja)

    old_ref = params.get("ref_audio_path")
    old_prompt = params.get("prompt_text")
    old_speed = params.get("speed_factor")
    params["ref_audio_path"] = wav
    if prompt:
        params["prompt_text"] = prompt
    if emo in EMO_SPEED:
        params["speed_factor"] = EMO_SPEED[emo]
    try:
        logger.info(f"[tts_ja] 情绪 {emo} → {os.path.basename(wav)}")
        return await _ORIG(self, ja)
    finally:
        if old_ref is not None:
            params["ref_audio_path"] = old_ref
        if old_prompt is not None and prompt:
            params["prompt_text"] = old_prompt
        if old_speed is not None:
            params["speed_factor"] = old_speed


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        global _CTX, _ORIG
        self.context = context
        _CTX = context
        _init_ref_dir()

        if getattr(ProviderGSVTTS, "_tts_ja_patched", False):
            logger.info("[tts_ja] 已经打过补丁，跳过")
            return

        if not hasattr(ProviderGSVTTS, "get_audio"):
            logger.error("[tts_ja] 找不到 get_audio，插件未生效")
            return

        _ORIG = ProviderGSVTTS.get_audio
        ProviderGSVTTS.get_audio = _get_audio
        ProviderGSVTTS._tts_ja_patched = True
        logger.info("[tts_ja] 已生效：语音合成前自动把中文翻成日语")
