"""群友画像 + 会话滚动摘要。

抄的是两个成熟项目的思路：
- 麦麦 MaiBot 的「永远都在更加了解你」：给每个群友维护一份长期画像，
  而不是只靠最近 50 条群聊的裸窗口。
- KouriChat 的「用小模型定期整理记忆」：攒一批新消息后用一次便宜的
  LLM 调用提炼稳定事实，合并进画像文件。

两件事：

1) 群友画像
   观察所有群消息（含她自己的回复）→ 每 30 分钟（且攒够 15 条新料）
   用 DeepSeek 提炼「值得长期记住的稳定信息」→ 存 profiles.json →
   在每次 LLM 请求前把画像注入为临时提示（不进历史，不烧 token）。

2) 会话滚动摘要
   对话历史超过 40 条时，把最老的一段压成 ≤120 字备忘，累积保存在
   summaries.json，请求里只保留最近 20 条 + 备忘。内核是"按发送内容
   存历史"，所以截断必须由我们自己管累积摘要，否则丢了就是真丢了。

画像和摘要都用当前对话模型（DeepSeek），无新增 API。
"""

import asyncio
import io
import json
import os
import re
import time
import uuid

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.platform import MessageType
from astrbot.core.agent.message import TextPart

# ---------------- 可调参数 ----------------
DISTILL_INTERVAL = 1800   # 画像提炼周期（秒）
DISTILL_MIN_LINES = 15    # 新消息不足这么多就不花这次调用
PROFILE_MAX_FACTS = 20    # 每人最多保留多少条画像
PROFILE_STALE_DAYS = 14   # 超过这么多天没发言的画像不再注入
INJECT_MAX_CHARS = 800    # 画像注入总字数上限
SUMMARY_THRESHOLD = 40    # 会话历史超过这个条数才触发摘要
SUMMARY_KEEP = 20         # 摘要后保留最近多少条
SUMMARY_MAX_CHARS = 600   # 累计备忘字数上限
LINES_MAX = 2000          # 原始记录最多存多少行
# ------------------------------------------

DISTILL_PROMPT = """下面是一个QQ群最近的聊天记录（JSON 行，每行一条，"都(bot)"是虚拟角色九条都的发言）。

请为其中发言较多的人提炼「值得长期记住的稳定信息」。每条事实前面加类别标签：
- 【身份】自曝的稳定信息：学校/工作/宠物/所在城市等
- 【偏好】明确表达过的喜好或讨厌
- 【经历】共同发生过的事、约定、梗的来历
- 【梗】群里的称呼、黑话、只属于这个人的梗
- 【更正】新信息推翻了旧认知时才用；格式：【更正】新认知（原以为：旧认知关键词）

要求：
- 不要记录一次性事件和寒暄，不要编造，宁缺毋滥
- 事实要具体："在准备考研" 而不是 "在忙"
- 和别人聊天时说的设定/玩笑/角色扮演，不要当成这个人的真实信息

只输出 JSON，格式：{"昵称": ["【偏好】...", "..."]}，每人最多 5 条。"""

SUMMARY_PROMPT = """把下面这段对话压缩成不超过 120 字的备忘。保留：人物、达成的结论、承诺过的事、没聊完的话题、明显的情绪转折。直接输出备忘，不要解释。"""

PROFILE_HEADER = "[群友画像——你的长期观察，供参考。不要复述，不要承认在查资料]"
SUMMARY_HEADER = "[此前对话的备忘——更早的聊天已压缩成这样]"


def _extract_json(text: str):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _atomic_write(path: str, data) -> None:
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _load_json(path: str, default):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        self._dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(self._dir, exist_ok=True)
        self._lines_path = os.path.join(self._dir, "lines.jsonl")
        self._profiles_path = os.path.join(self._dir, "profiles.json")
        self._summaries_path = os.path.join(self._dir, "summaries.json")
        self._pending: list[str] = []       # 待提炼的新消息行
        self._summaries: dict = _load_json(self._summaries_path, {})
        self._lock = asyncio.Lock()
        self._task = asyncio.create_task(self._distill_loop())
        n = sum(len(v.get("facts", [])) for v in _load_json(self._profiles_path, {}).values())
        logger.info(f"[mem] 群友画像已生效（存量 {n} 条），摘要阈值 {SUMMARY_THRESHOLD} 条")

    async def terminate(self):
        self._task.cancel()

    # ---------------- 观察 ----------------

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL, priority=-1)
    async def observe(self, event: AstrMessageEvent):
        if event.get_message_type() != MessageType.GROUP_MESSAGE:
            return
        text = (event.message_str or "").strip()
        if not text:
            return
        line = json.dumps(
            {
                "t": time.strftime("%m-%d %H:%M"),
                "name": event.get_sender_name(),
                "text": text[:120],
            },
            ensure_ascii=False,
        )
        await self._record(line)

    @filter.on_llm_response()
    async def observe_bot(self, event: AstrMessageEvent, response) -> None:
        if event.get_message_type() != MessageType.GROUP_MESSAGE:
            return
        text = (getattr(response, "completion_text", "") or "").strip()
        if not text:
            return
        await self._record(
            json.dumps(
                {"t": time.strftime("%m-%d %H:%M"), "name": "都(bot)", "text": text[:120]},
                ensure_ascii=False,
            ),
        )

    async def _record(self, line: str) -> None:
        async with self._lock:
            self._pending.append(line)
            try:
                with io.open(self._lines_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as e:
                logger.error(f"[mem] 写记录失败: {e}")

    # ---------------- 注入 ----------------

    @filter.on_llm_request()
    async def inject(self, event: AstrMessageEvent, req) -> None:
        try:
            await self._inject_profiles(event, req)
            await self._rolling_summary(event, req)
        except Exception as e:
            logger.error(f"[mem] 注入失败: {e}")

    async def _inject_profiles(self, event, req) -> None:
        profiles = _load_json(self._profiles_path, {})
        if not profiles:
            return
        now = time.time()
        blocks, total = [], 0
        for name, p in sorted(
            profiles.items(),
            key=lambda kv: -kv[1].get("updated", 0),
        ):
            if now - p.get("updated", 0) > PROFILE_STALE_DAYS * 86400:
                continue
            facts = p.get("facts", [])[-4:]
            # 更正条目优先展示，避免她还在用被推翻的旧认知
            facts.sort(key=lambda f: 0 if f.startswith("【更正】") else 1)
            if not facts:
                continue
            block = f"- {name}：{'；'.join(facts)}"
            if total + len(block) > INJECT_MAX_CHARS:
                break
            blocks.append(block)
            total += len(block)
        if not blocks:
            return
        req.extra_user_content_parts.append(
            TextPart(text=PROFILE_HEADER + "\n" + "\n".join(blocks)).mark_as_temp(),
        )

    async def _rolling_summary(self, event, req) -> None:
        ctx = req.contexts or []
        cid = req.conversation.cid if req.conversation else event.unified_msg_origin

        # 关键：已有摘要每轮都要重新注入，否则压缩过一次之后下一轮就"失忆"了
        if self._summaries.get(cid):
            req.extra_user_content_parts.append(
                TextPart(text=SUMMARY_HEADER + "\n" + self._summaries[cid]).mark_as_temp(),
            )

        if len(ctx) <= SUMMARY_THRESHOLD:
            return
        old, recent = ctx[:-SUMMARY_KEEP], ctx[-SUMMARY_KEEP:]
        if len(old) < 6:
            return

        prov = await self.context.get_using_provider_async(event.unified_msg_origin)
        if not prov:
            return

        dump = "\n".join(
            f"{m.get('role', '?')}: {str(m.get('content', ''))[:150]}" for m in old
        )
        try:
            resp = await prov.text_chat(
                prompt=dump[:6000],
                system_prompt=SUMMARY_PROMPT,
                session_id=uuid.uuid4().hex,
                contexts=[],
                persist=False,
            )
            piece = (resp.completion_text or "").strip()
        except Exception as e:
            logger.error(f"[mem] 摘要失败，本次硬截断: {e}")
            piece = ""

        if piece:
            merged = (self._summaries.get(cid, "") + "\n" + piece).strip()
            if len(merged) > SUMMARY_MAX_CHARS:
                merged = "……\n" + merged[-SUMMARY_MAX_CHARS:]
            self._summaries[cid] = merged
            _atomic_write(self._summaries_path, self._summaries)
            req.extra_user_content_parts.append(
                TextPart(text=SUMMARY_HEADER + "\n" + merged).mark_as_temp(),
            )
            logger.info(f"[mem] 会话 {cid[:8]} 滚动摘要完成，丢 {len(old)} 条留 {SUMMARY_KEEP} 条")

        req.contexts = recent

    # ---------------- 后台提炼 ----------------

    async def _distill_loop(self):
        while True:
            try:
                await asyncio.sleep(DISTILL_INTERVAL)
                self._trim_lines_file()
                async with self._lock:
                    # 先看够不够阈值，够了才取走；不够就留着继续攒，
                    # 否则安静群每次少量新材料会被直接丢弃
                    if len(self._pending) < DISTILL_MIN_LINES:
                        continue
                    batch, self._pending = self._pending[:], []
                await self._distill(batch)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"[mem] 提炼循环异常: {e}")

    async def _distill(self, batch: list[str]) -> None:
        prov = await self.context.get_using_provider_async()
        if not prov:
            return
        prompt = "\n".join(batch)[:8000]
        try:
            resp = await prov.text_chat(
                prompt=prompt,
                system_prompt=DISTILL_PROMPT,
                session_id=uuid.uuid4().hex,
                contexts=[],
                persist=False,
            )
        except Exception as e:
            logger.error(f"[mem] 提炼调用失败: {e}")
            return
        data = _extract_json(resp.completion_text)
        if not data:
            logger.warning(f"[mem] 提炼结果不是 JSON: {resp.completion_text[:80]}")
            return

        profiles = _load_json(self._profiles_path, {})
        now = time.time()
        changed = 0
        for name, facts in data.items():
            if not isinstance(facts, list):
                continue
            p = profiles.setdefault(name, {"facts": [], "updated": 0})
            exist = p.get("facts", [])
            for f in facts:
                f = str(f).strip()[:80]
                if not f:
                    continue
                # 更正条目：把被推翻的旧认知删掉（按"原以为：关键词"匹配）
                m = re.search(r"（原以为[:：](.+?)）", f)
                if m and f.startswith("【更正】"):
                    old_key = m.group(1).strip()
                    before = len(exist)
                    exist = [e for e in exist if old_key not in e]
                    removed = before - len(exist)
                    if removed:
                        logger.info(f"[mem] {name} 更正记忆，移除 {removed} 条含『{old_key}』")
                if f not in exist and not any(f in e for e in exist):
                    exist.append(f)
                    changed += 1
            p["facts"] = exist[-PROFILE_MAX_FACTS:]
            p["updated"] = now
        _atomic_write(self._profiles_path, profiles)
        logger.info(f"[mem] 画像更新：{len(data)} 人，新增 {changed} 条")

    # 顺手把原始记录文件裁到上限
    def _trim_lines_file(self):
        try:
            with io.open(self._lines_path, encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > LINES_MAX:
                with io.open(self._lines_path, "w", encoding="utf-8") as f:
                    f.writelines(lines[-LINES_MAX:])
        except Exception:
            pass

    # ---------------- 记忆治理（管理员指令） ----------------
    # memory-board 的核心思想：记忆必须可查看、可纠正，不能是黑箱。
    # 她记错了东西，管理员当场改，而不是等 dream 整理碰运气。

    @filter.command("都记忆")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_show_memory(self, event: AstrMessageEvent):
        """查看她的群友画像：/都记忆 或 /都记忆 某人"""
        # 框架的命令过滤器只在自己的局部变量里去掉命令名，
        # event.message_str 仍然带着「都记忆」，所以这里手动剥掉
        query = re.sub(r"^\s*都记忆\s*", "", event.message_str or "").strip()
        profiles = _load_json(self._profiles_path, {})
        if not profiles:
            yield event.plain_result("（她还没记住任何人的事）")
            return
        lines = []
        for name, p in sorted(profiles.items(), key=lambda kv: -kv[1].get("updated", 0)):
            if query and query not in name:
                continue
            facts = p.get("facts", [])
            if not facts:
                continue
            when = time.strftime("%m-%d", time.localtime(p.get("updated", 0)))
            lines.append(f"◆ {name}（{when} 更新）")
            for f in facts:
                lines.append(f"  {f}")
            lines.append("")
        if not lines:
            yield event.plain_result(f"没有匹配『{query}』的记忆")
        else:
            text = "\n".join(lines).strip()
            yield event.plain_result(text[:3000] if len(text) > 3000 else text)

    @filter.command("都忘掉")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_forget_memory(self, event: AstrMessageEvent):
        """删掉记错的事：/都忘掉 昵称 关键词（或 /都忘掉 昵称 全部）"""
        arg = re.sub(r"^\s*都忘掉\s*", "", event.message_str or "").strip()
        parts = arg.split(None, 1)
        if len(parts) < 2:
            yield event.plain_result("用法：/都忘掉 昵称 关键词")
            return
        name, key = parts[0].strip(), parts[1].strip()
        profiles = _load_json(self._profiles_path, {})
        target = None
        for n in profiles:
            if name in n:
                target = n
                break
        if not target:
            yield event.plain_result(f"画像里没有叫『{name}』的人：{'、'.join(profiles) or '（空）'}")
            return
        facts = profiles[target].get("facts", [])
        if key == "全部":
            profiles[target]["facts"] = []
            removed = len(facts)
        else:
            keep = [f for f in facts if key not in f]
            removed = len(facts) - len(keep)
            profiles[target]["facts"] = keep
        _atomic_write(self._profiles_path, profiles)
        yield event.plain_result(f"好，{target} 的记忆删掉了 {removed} 条（关键词：{key}）")
