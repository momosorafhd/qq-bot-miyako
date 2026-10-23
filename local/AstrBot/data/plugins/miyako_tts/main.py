"""都的语音：生成台词制，不做翻译。

旧逻辑的问题：中文回复先"机翻"成日语再合成，翻出来的东西一股翻译腔，
怎么调 prompt 都救不回来——翻译本身就是错的。

新逻辑：让模型在**写回复的时候**就同时写出她的日语台词。对模型来说这
不是"把这句话翻译成日语"，而是"给这条回复配一段她的日文台词"——语气词、
停顿、口语缩约都在生成时就带上了，然后 TTS 直接拿台词合成：

  LLM 生成 ──→ 中文正文（发出去的文字）
           └─→ [ja:……] 日语台词 → GSV 合成 → Record 语音

链路全部走官方钩子：
  on_llm_request     注入"台词格式"指令（临时，不进历史）
  on_llm_response    抠出 [ja:...] 存到 event extra
  on_decorating_result  从正文剥掉标记 + 合成 + 插 Record（双输出）

内核自带的 TTS 必须保持关闭（provider_tts_settings.enable=false），
否则会双重语音。内核的 gsv-miyako Provider 仍然注册着，启动时照常
把权重推给 9880，这里是复用它的配置和参考音。

台词缺失时（模型偶尔没按格式写）回退为旧的 LLM 翻译，保证有声音。
"""

import hashlib
import os
import re
import time
import uuid

import aiohttp

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.platform import MessageType
from astrbot.core.agent.message import TextPart
from astrbot.core.message.components import Plain, Record
from astrbot.core.provider.sources.gsv_selfhosted_source import ProviderGSVTTS
from astrbot.core.provider.register import (
    provider_cls_map,
    provider_registry,
    register_provider_adapter,
)
from astrbot.core.provider.entities import ProviderType

# ---------------- 可调参数 ----------------
VOICE_RATE = 1.0        # 带语音的比例（1.0 = 每条都配）
JA_LINE_MAX = 220       # 台词长度保护
SYNTH_TIMEOUT = 60
# ------------------------------------------

# 生成时追加的"台词"指令。关键：不是翻译，是配音。
LINE_PROMPT = """
[输出格式补充要求]
写完中文回复后，另起一行，在最后加上她的日语台词，格式严格为：
[ja:台词]
台词要求：把这条回复用她的口吻写成日语口语——这是给角色配音的台词，不是翻译。
要自然、有语气词（えっと/うん/ね/……），可以有点小傲娇，不要敬语连发，不要书面语。
只输出台词本身，不要加引号和解释。
"""

# ---------------- 翻译（仅作兜底） ----------------
FALLBACK_TRANSLATE_PROMPT = """你是中文到日语的翻译。把中文翻成自然的日语口语。
只输出译文。用年轻女性的口语，语气软、略犹豫，可以保留"……"。不要敬语连发。
如果原文就是日语，原样返回。"""

# ---------------- 情绪参考音频 ----------------
EMO_RULES = {
    "happy": ("哈哈", "笑", "太好了", "开心", "嘿嘿", "好玩", "棒", "耶"),
    "shy": ("对不起", "不好意思", "抱歉", "害羞", "脸红", "唔", "那个"),
    "sad": ("难过", "累", "唉", "算了", "孤单", "想哭", "失落"),
}
EMO_SPEED = {"happy": "1.05", "shy": "0.93", "sad": "0.88"}
REF_DIR = None
_REF_CACHE: dict[str, tuple[str, str]] = {}

JA_RE = re.compile(r"\[ja[:：]\s*(.*?)\s*\]", re.S)
JA_FRAGMENT_RE = re.compile(r"\[ja[:：][^\]]*\]?")

_CTX = None
_GSV_CFG: dict | None = None  # gsv_source 的配置（api_base、默认参数）
_TTS_CACHE: dict[str, str] = {}
_CACHE_MAX = 200


def _init_paths() -> None:
    global REF_DIR
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        cand = os.path.join(cur, "voice", "ref")
        if os.path.isdir(cand):
            REF_DIR = cand
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    if not REF_DIR:
        logger.warning("[miyako_tts] 没找到 voice/ref，情绪音频不会生效")


def _load_gsv_cfg() -> None:
    global _GSV_CFG
    try:
        d = _CTX.get_config()
        for s in d.get("provider_sources", []):
            if s.get("id") == "gsv_source":
                _GSV_CFG = s
                return
    except Exception as e:
        logger.error(f"[miyako_tts] 读 gsv_source 配置失败: {e}")
    logger.warning("[miyako_tts] 未找到 gsv_source，语音不会生效")


def _ref_for(emo: str) -> tuple[str, str] | None:
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
    best, best_score = None, 0
    for emo, words in EMO_RULES.items():
        score = sum(1 for w in words if w in text)
        if score > best_score:
            best, best_score = emo, score
    return best


def _has_kana(text: str) -> bool:
    return any("\u3040" <= c <= "\u30ff" for c in text)


# ---------------- GSV 合成 ----------------

async def _gsv_synth(ja: str, speed: str | None, ref: tuple[str, str] | None) -> str:
    """调 GSV /tts，返回 wav 路径。"""
    cfg = _GSV_CFG or {}
    params = {
        k.removeprefix("gsv_"): str(v).lower()
        for k, v in (cfg.get("gsv_default_parms") or {}).items()
    }
    params["text"] = ja
    params["text_lang"] = "ja"
    params["prompt_lang"] = "ja"
    if ref:
        params["ref_audio_path"] = ref[0]
        if ref[1]:
            params["prompt_text"] = ref[1]
    if speed:
        params["speed_factor"] = speed

    base = str(cfg.get("api_base", "http://127.0.0.1:9880")).rstrip("/")
    cache_key = hashlib.sha1(
        (ja + "|" + str(speed) + "|" + str(params.get("ref_audio_path"))).encode()
    ).hexdigest()
    if cache_key in _TTS_CACHE:
        return _TTS_CACHE[cache_key]

    timeout = aiohttp.ClientTimeout(total=SYNTH_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{base}/tts", params=params) as resp:
            if resp.status != 200:
                raise RuntimeError(f"GSV {resp.status}: {(await resp.text())[:120]}")
            data = await resp.read()
    if len(data) < 2000:
        raise RuntimeError(f"GSV 返回异常小({len(data)}B)")

    from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
    from astrbot.core.utils.datetime_utils import generate_timestamp_id

    path = os.path.join(get_astrbot_temp_path(), f"miyako_{generate_timestamp_id()}.wav")
    with open(path, "wb") as f:
        f.write(data)
    if len(_TTS_CACHE) < _CACHE_MAX:
        _TTS_CACHE[cache_key] = path
    return path


async def _fallback_translate(text: str) -> str:
    """模型没写台词时的兜底：LLM 翻译（有翻译腔，但保证有声音）。"""
    text = (text or "").strip()
    if not text or _has_kana(text):
        return text
    try:
        provider = _CTX.get_using_provider() if _CTX else None
        if not provider:
            return text
        resp = await provider.text_chat(
            prompt=text[:300], system_prompt=FALLBACK_TRANSLATE_PROMPT, contexts=[]
        )
        ja = (resp.completion_text or "").strip().strip("「」")
        return ja if _has_kana(ja) else text
    except Exception as e:
        logger.error(f"[miyako_tts] 兜底翻译失败: {e}")
        return text


# ---------------- Provider（保留注册，启动时负责推权重） ----------------

if provider_cls_map.pop("miyako_gsv_tts", None) is not None:
    provider_registry[:] = [p for p in provider_registry if p.type != "miyako_gsv_tts"]


@register_provider_adapter(
    provider_type_name="miyako_gsv_tts",
    desc="GPT-SoVITS（都：台词制语音）",
    provider_type=ProviderType.TEXT_TO_SPEECH,
)
class MiyakoGSVTTS(ProviderGSVTTS):
    """仅在手动重新启用内核 TTS 时才会被调用（不推荐，会双重语音）。"""

    async def get_audio(self, text: str) -> str:
        ja = await _fallback_translate(text)
        return await _gsv_synth(ja, None, None)


# ---------------- 插件主体 ----------------

class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        global _CTX
        _CTX = context
        _init_paths()
        _load_gsv_cfg()
        logger.info(
            "[miyako_tts] 台词制语音已生效：LLM 直接产出日语台词，不再机翻"
            f"（voice_rate={VOICE_RATE}，gsv={(_GSV_CFG or {}).get('api_base')}）",
        )

    # 1) 生成前：追加台词格式要求
    @filter.on_llm_request()
    async def ask_for_line(self, event: AstrMessageEvent, req) -> None:
        try:
            req.extra_user_content_parts.append(
                TextPart(text=LINE_PROMPT).mark_as_temp(),
            )
        except Exception as e:
            logger.error(f"[miyako_tts] 注入台词指令失败: {e}")

    # 2) 生成后：抠台词
    @filter.on_llm_response()
    async def harvest_line(self, event: AstrMessageEvent, response) -> None:
        text = (getattr(response, "completion_text", "") or "")
        m = JA_RE.search(text)
        if m:
            ja = m.group(1).strip()[:JA_LINE_MAX]
            if ja and _has_kana(ja):
                event.set_extra("_miyako_ja", ja)

    # 3) 发送前：剥标记 + 合成 + 插语音
    @filter.on_decorating_result()
    async def attach_voice(self, event: AstrMessageEvent):
        result = event.get_result()
        if result is None or not result.chain:
            return
        if not result.is_llm_result():
            return

        # 剥掉正文里的台词标记
        body_text = ""
        for comp in result.chain:
            if isinstance(comp, Plain):
                comp.text = JA_FRAGMENT_RE.sub("", comp.text).replace("\n\n\n", "\n\n").strip()
                body_text += comp.text

        ja = event.get_extra("_miyako_ja")
        if not ja and body_text:
            ja = await _fallback_translate(body_text)
        if not ja or not _has_kana(ja):
            return
        if VOICE_RATE < 1.0:
            import random

            if random.random() > VOICE_RATE:
                return

        emo = _pick_emotion(body_text or ja)
        try:
            path = await _gsv_synth(
                ja,
                EMO_SPEED.get(emo) if emo else None,
                _ref_for(emo) if emo else None,
            )
        except Exception as e:
            logger.error(f"[miyako_tts] 合成失败，本次纯文字: {e}")
            return
        logger.info(f"[miyako_tts] 台词({emo or 'normal'}) {ja[:30]}")
        result.chain.append(Record(file=path, url=path, text=(body_text or ja)[:50]))
