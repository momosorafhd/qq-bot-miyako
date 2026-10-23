import asyncio
import copy
import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from support import At, AtAll, Context, Event, Plain, Provider, Reply, ROOT, collect, load_plugin


class DialogueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mod = load_plugin('willingness_gate')
        self.mod.DATA_DIR = self.temp.name
        for name in ('COLD_QUIET', 'COLD_MAX_WAIT', 'WARM_QUIET', 'WARM_MAX_WAIT',
                     'BUSY_QUIET', 'BUSY_MAX_WAIT', 'COLD_COOLDOWN', 'WARM_COOLDOWN'):
            setattr(self.mod, name, 0)
        self.context = Context()
        self.bot = self.mod.Main(self.context)

    async def test_other_mentions_and_quotes_are_observed_without_generation(self):
        for parts in ([At('2')], [Reply('2')], [AtAll()]):
            event = Event(parts=parts, wake=True)
            self.assertEqual(await collect(self.bot.gate(event)), [])
            self.assertTrue(event.call_llm)
            self.assertFalse(event.stopped)  # 不截断原始观察流水线
        self.assertEqual(self.context.provider.calls, [])

    async def test_direct_bot_at_uses_native_path_once(self):
        event = Event(parts=[At('99'), Reply('2')], wake=True)
        self.assertEqual(await collect(self.bot.gate(event)), [])
        self.assertEqual(event.get_extra('_miyako_address'), 'bot')
        self.assertFalse(event.call_llm)

    async def test_name_in_report_is_not_an_automatic_ten(self):
        self.context.provider.result = '{"addressed_to":"other","action":"reply","score":10,"next_threshold":9}'
        self.assertEqual(await collect(self.bot.gate(Event('我刚和小都聊过，明天你去吗'))), [])
        self.assertEqual(len(self.context.provider.calls), 1)

    async def test_name_address_warms_attention_but_still_needs_model(self):
        self.assertEqual(len(await collect(self.bot.gate(Event('小都，你吃了吗')))), 1)
        self.assertEqual(len(self.context.provider.calls), 1)
        self.assertEqual(self.bot._attention('qq:GroupMessage:A', self.mod.time.monotonic())['mode'], 'warm')

    async def test_high_uncertain_score_is_still_silent(self):
        self.context.provider.result = '{"addressed_to":"unclear","action":"reply","score":10,"next_threshold":4}'
        self.assertFalse(await collect(self.bot.gate(Event())))

    async def test_decision_schema_rejects_numbers_boolean_and_extra_prose(self):
        for text in ('10', '{"addressed_to":"public","score":true}',
                     '建议回复 {"addressed_to":"public","score":9}',
                     '{"addressed_to":"public","score":11}'):
            self.assertEqual(self.mod._decision(text)['action'], 'listen')

    async def test_concurrent_candidate_does_not_start_second_call(self):
        release = self.context.provider.wait = asyncio.Event()
        first = asyncio.create_task(collect(self.bot.gate(Event(mid='a'))))
        await asyncio.sleep(0)
        second = asyncio.create_task(collect(self.bot.gate(Event(mid='b'))))
        await asyncio.sleep(0)
        self.assertEqual(len(self.context.provider.calls), 1)
        release.set()
        self.assertEqual(await first, [])  # 旧事件不能继续按旧对象发言
        self.assertEqual(len(await second), 1)
        self.assertEqual(len(self.context.provider.calls), 2)
        self.assertFalse(self.bot._evaluating)

    async def test_native_direct_turn_invalidates_old_assessment(self):
        release = self.context.provider.wait = asyncio.Event()
        first = asyncio.create_task(collect(self.bot.gate(Event(mid='a'))))
        await asyncio.sleep(0)
        await collect(self.bot.gate(Event(parts=[At('99')], mid='b', wake=True)))
        release.set()
        self.assertEqual(await first, [])

    async def test_score_timeout_fails_closed_and_releases_inflight(self):
        self.mod.EVALUATION_TIMEOUT = 0.001
        self.context.provider.wait = asyncio.Event()
        self.assertEqual(await collect(self.bot.gate(Event())), [])
        self.assertFalse(self.bot._evaluating)

    async def test_independent_channel_and_usage_logging(self):
        self.mod.SCORE_PROVIDER_ID = 'intent-model'
        self.assertEqual(len(await collect(self.bot.gate(Event()))), 1)
        self.assertEqual(self.context.selected, ['intent-model'])
        records = [json.loads(s) for s in Path(self.bot._log_path).read_text(encoding='utf-8').splitlines()]
        scores = [r for r in records if r['purpose'] == 'score']
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0]['usage']['input_cached'], 10)
        self.assertNotIn('text', scores[0])

    async def test_proactive_generator_can_abstain_before_other_hooks(self):
        event = Event()
        await collect(self.bot.gate(event))
        self.assertFalse(event.get_extra('enable_streaming'))
        req = NS(extra_user_content_parts=[])
        await self.bot.bind_target(event, req)
        self.assertTrue(any(self.mod.ABSTAIN_TOKEN in p.text for p in req.extra_user_content_parts))
        response = NS(completion_text=self.mod.ABSTAIN_TOKEN + '\n[ja:うん]')
        await self.bot.abstain(event, response)
        self.assertTrue(event.stopped)
        self.assertEqual(response.completion_text, '')
        self.assertGreater(self.bot.abstain.priority, self.bot.observe_bot.priority)

    async def test_default_random_path_cannot_bypass_intent_gate(self):
        event = Event()
        await self.bot.bind_target(event, NS(extra_user_content_parts=[]))
        self.assertTrue(event.stopped)

    async def test_bot_reply_and_its_target_are_in_next_assessment(self):
        event = Event(parts=[At('99')], wake=True)
        await collect(self.bot.gate(event))
        await self.bot.observe_bot(event, NS(completion_text='你到家了吗？[ja:帰った？]'))
        self.bot._last_speak.clear()
        await collect(self.bot.gate(Event('到了', mid='b')))
        records = json.loads(self.context.provider.calls[-1]['prompt'].split('聊天JSON：\n', 1)[1])['messages']
        self.assertTrue(any(r.get('reply_to_user') == '1' for r in records))

    async def test_evaluation_budget_caps_silent_calls(self):
        self.mod.MAX_EVALUATIONS_PER_MINUTE = 2
        self.context.provider.result = '{"addressed_to":"other","action":"listen","score":10,"next_threshold":9}'
        for i in range(3):
            await collect(self.bot.gate(Event(mid=str(i))))
        self.assertEqual(len(self.context.provider.calls), 2)

    async def test_cold_burst_is_batched_until_quiet(self):
        self.mod.COLD_QUIET, self.mod.COLD_MAX_WAIT = 0.02, 0.1
        first = asyncio.create_task(collect(self.bot.gate(Event('大家周末去哪', mid='a'))))
        await asyncio.sleep(0)
        second = asyncio.create_task(collect(self.bot.gate(Event('想去公园', mid='b'))))
        self.assertEqual(await first, [])
        self.assertEqual(len(await second), 1)
        self.assertEqual(len(self.context.provider.calls), 1)
        payload = json.loads(self.context.provider.calls[0]['prompt'].split('聊天JSON：\n', 1)[1])
        self.assertEqual([r['message_id'] for r in payload['messages']], ['a', 'b'])

    async def test_mandatory_at_bypasses_budget_cooldown_and_listen(self):
        self.mod.MAX_EVALUATIONS_PER_MINUTE = 0
        self.mod.WARM_COOLDOWN = 999
        self.bot._last_speak['qq:GroupMessage:A'] = self.mod.time.monotonic()
        event = Event(parts=[At('99')], wake=False)
        await collect(self.bot.gate(event))
        self.assertTrue(event.is_at_or_wake_command)
        self.assertFalse(event.call_llm)
        req = NS(extra_user_content_parts=[])
        await self.bot.bind_target(event, req)
        self.assertFalse(event.stopped)
        response = NS(completion_text=self.mod.ABSTAIN_TOKEN)
        await self.bot.abstain(event, response)
        self.assertFalse(event.stopped)  # 旁听机制不能撤销明确召唤
        self.assertEqual(self.context.provider.calls, [])

    async def test_new_other_target_cancels_waiting_batch(self):
        self.mod.COLD_QUIET, self.mod.COLD_MAX_WAIT = 0.1, 0.2
        first = asyncio.create_task(collect(self.bot.gate(Event(mid='a'))))
        await asyncio.sleep(0)
        await collect(self.bot.gate(Event(parts=[At('2')], mid='b')))
        self.assertEqual(await first, [])
        self.assertEqual(self.context.provider.calls, [])

    async def test_threshold_adapts_only_for_future_and_expires(self):
        self.context.provider.result = '{"addressed_to":"public","action":"reply","score":6,"next_threshold":4}'
        self.assertEqual(await collect(self.bot.gate(Event(mid='a'))), [])  # 当前7分不能自行降分通过
        now = self.mod.time.monotonic()
        self.assertEqual(self.bot._attention('qq:GroupMessage:A', now)['threshold'], 6)
        self.assertEqual(len(await collect(self.bot.gate(Event(mid='b')))), 1)
        self.assertEqual(self.bot._attention('qq:GroupMessage:A', now + self.mod.ADAPTATION_TTL + 1)['threshold'], 7)
        self.bot._adapt('qq:GroupMessage:A', {'next_threshold': -100}, 4, now)
        self.assertGreaterEqual(self.bot._attention('qq:GroupMessage:A', now)['threshold'], 4)

    async def test_mention_heat_expires_and_bot_cannot_extend_it(self):
        event = Event('我记得小都也喜欢这个')
        await collect(self.bot.gate(event))
        scope, now = event.unified_msg_origin, self.mod.time.monotonic()
        expiry = self.bot._warm_until[scope]
        await self.bot.observe_bot(event, NS(completion_text='嗯，我听着呢'))
        self.assertEqual(self.bot._warm_until[scope], expiry)
        self.assertEqual(self.bot._attention(scope, now)['mode'], 'warm')
        self.assertEqual(self.bot._attention(scope, expiry + 1)['mode'], 'cold')

    async def test_model_listen_and_long_incomplete_messages_do_not_generate(self):
        self.context.provider.result = '{"addressed_to":"public","action":"listen","score":10,"next_threshold":7}'
        self.assertFalse(await collect(self.bot.gate(Event())))
        self.context.provider.result = '{"addressed_to":"bot","action":"reply","score":10,"next_threshold":5}'
        self.assertFalse(await collect(self.bot.gate(Event('很长' * 500, mid='long'))))

    async def test_group_activity_is_not_invitation_and_groups_are_isolated(self):
        scope, now = 'qq:GroupMessage:A', self.mod.time.monotonic()
        self.bot._arrivals[scope] = [now] * 8
        self.assertEqual(self.bot._attention(scope, now)['mode'], 'cold')
        self.assertEqual(self.bot._attention(scope, now)['threshold'], 8)
        self.assertEqual(self.bot._attention('qq:GroupMessage:B', now)['threshold'], 7)

    async def test_hot_and_cold_wait_have_finite_batch_deadlines(self):
        self.mod.COLD_QUIET, self.mod.COLD_MAX_WAIT = 10, 30
        self.mod.WARM_QUIET, self.mod.WARM_MAX_WAIT = 1.5, 6
        scope = 'qq:GroupMessage:A'
        self.assertEqual(self.bot._delay(scope, 0, 29), 1)
        self.bot._warm_until[scope] = 200
        self.assertEqual(self.bot._delay(scope, 0, 5), 1)

    async def test_generation_abstention_does_not_record_bot_or_cooldown(self):
        event = Event()
        await collect(self.bot.gate(event))
        response = NS(completion_text=self.mod.ABSTAIN_TOKEN)
        await self.bot.abstain(event, response)
        await self.bot.observe_bot(event, response)
        self.assertNotIn(event.unified_msg_origin, self.bot._last_speak)
        self.assertFalse(any(r.get('kind') == 'generated_bot_reply'
                             for r in self.bot._lines[event.unified_msg_origin]))

    async def test_new_at_supersedes_already_generating_proactive_reply(self):
        event = Event(mid='old')
        await collect(self.bot.gate(event))
        await collect(self.bot.gate(Event(parts=[At('99')], mid='new')))
        response = NS(completion_text='旧话题的回答')
        await self.bot.abstain(event, response)
        self.assertTrue(event.stopped)
        self.assertEqual(response.completion_text, '')

    async def test_new_group_creates_a_bound_conversation_for_persona_and_history(self):
        with patch.object(self.context, 'get_curr_conversation_id', AsyncMock(return_value=None)):
            result = await collect(self.bot.gate(Event()))
        self.assertEqual(result[0]['conversation'].cid, 'new-conv')


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mod = load_plugin('memory_distill')
        self.mod.DATA_DIR = self.temp.name
        self.context = Context(Provider('{"updates":[]}'))
        self.bots = []
        self.bot = self.new_bot()

    def new_bot(self):
        bot = self.mod.Main(self.context)
        self.bots.append(bot)
        return bot

    async def asyncTearDown(self):
        for bot in self.bots:
            await bot.terminate()

    async def record(self, count=1, scope='qq:GroupMessage:A', user='1', text='我不喜欢香菜'):
        for _ in range(count):
            mid = str(self.bot._seq + 1)
            await self.bot.observe(Event(text, scope=scope, user=user, mid=mid))

    def extraction(self, text='【偏好】不喜欢香菜', replaces=()):
        def respond(kwargs):
            batch = json.loads(kwargs['prompt'])['messages']
            row = batch[-1]
            return json.dumps({'updates': [{'user_id': row['user_id'], 'facts': [
                {'text': text, 'source_ids': [row['seq']], 'supersedes': list(replaces)}]}]}, ensure_ascii=False)
        self.context.provider.result = respond

    async def distill(self):
        return await self.bot._distill(self.bot._batch(), self.bot._epoch)

    async def test_pending_survives_restart_and_platform_replay_is_deduplicated(self):
        event = Event(mid='stable')
        await self.bot.observe(event)
        await self.bot.terminate()
        self.bot = self.new_bot()
        await self.bot.observe(event)
        self.assertEqual(len(self.bot._pending), 1)

    async def test_api_failure_keeps_pending_and_cursor(self):
        await self.record(15)
        self.context.provider.error = RuntimeError('offline')
        self.assertFalse(await self.distill())
        self.assertEqual(len(self.bot._pending), 15)
        self.assertEqual(self.bot._state['cursor'], 0)
        self.bot = self.new_bot()
        self.assertEqual(len(self.bot._pending), 15)

    async def test_invalid_json_is_not_acknowledged(self):
        await self.record(1)
        self.context.provider.result = 'not JSON'
        self.assertFalse(await self.distill())
        self.assertEqual(len(self.bot._pending), 1)

    async def test_long_batch_eventually_reaches_tail_without_truncation(self):
        await self.record(35, text='共同经历' * 120)
        while self.bot._pending:
            batch = self.bot._batch()
            self.assertTrue(batch)
            self.assertTrue(await self.distill())
        payloads = [json.loads(k['prompt']) for k in self.context.provider.calls]
        seqs = [r['seq'] for p in payloads for r in p['messages']]
        self.assertEqual(seqs, list(range(1, 36)))
        self.assertTrue(all(len(k['prompt']) <= self.mod.DISTILL_MAX_CHARS for k in self.context.provider.calls))

    async def test_success_and_profile_are_one_committed_state(self):
        await self.record()
        self.extraction()
        self.assertTrue(await self.distill())
        disk = json.loads(Path(self.bot._state_path).read_text(encoding='utf-8'))
        self.assertEqual(disk['cursor'], 1)
        self.assertIn(self.mod._key('qq:GroupMessage:A', '1'), disk['profiles'])
        self.assertFalse(self.new_bot()._pending)

    async def test_write_failure_does_not_acknowledge_or_change_live_profiles(self):
        await self.record()
        self.extraction()
        with patch.object(self.bot, '_save', side_effect=OSError('disk full')):
            self.assertFalse(await self.distill())
        self.assertFalse(self.bot._state['profiles'])
        self.assertEqual(len(self.bot._pending), 1)

    async def test_claim_of_another_users_message_is_rejected(self):
        await self.record(user='1')
        await self.record(user='2')
        self.context.provider.result = json.dumps({'updates': [{'user_id': '1', 'facts': [
            {'text': '【身份】伪造', 'source_ids': [2]}]}]})
        self.assertFalse(await self.distill())
        self.assertEqual(len(self.bot._pending), 2)

    async def test_same_name_separate_ids_and_no_cross_scope_injection(self):
        for scope, uid, fact in [('qq:GroupMessage:A', '1', '甲咖啡'), ('qq:GroupMessage:A', '2', '乙茶'),
                                 ('qq:GroupMessage:B', '1', '另一群信息')]:
            await self.record(scope=scope, user=uid)
            self.extraction('【偏好】' + fact)
            self.assertTrue(await self.distill())
        req = NS(extra_user_content_parts=[])
        self.bot._inject_profiles(Event(user='1'), req)
        body = '\n'.join(p.text for p in req.extra_user_content_parts)
        self.assertIn('甲咖啡', body)
        self.assertNotIn('乙茶', body)
        self.assertNotIn('另一群', body)
        self.assertIsNone(self.bot._resolve('qq:GroupMessage:A', '同名群友'))

    async def test_private_request_gets_no_group_profile(self):
        await self.record()
        self.extraction()
        await self.distill()
        req = NS(extra_user_content_parts=[], contexts=[], conversation=NS(cid='conv'))
        await self.bot.inject(Event(kind='private'), req)
        self.assertFalse(req.extra_user_content_parts)

    async def test_explicit_correction_sees_old_fact_and_replaces_it(self):
        await self.record()
        self.extraction('【偏好】喜欢咖啡')
        await self.distill()
        key = self.mod._key('qq:GroupMessage:A', '1')
        old = self.bot._state['profiles'][key]['facts'][0]['id']
        await self.record(text='我现在不喝咖啡，只喝茶')
        self.extraction('【偏好】不喝咖啡，只喝茶', replaces=[old])
        self.assertTrue(await self.distill())
        payload = json.loads(self.context.provider.calls[-1]['prompt'])
        self.assertEqual(payload['existing']['1'][0]['id'], old)
        self.assertEqual([f['text'] for f in self.bot._state['profiles'][key]['facts']], ['【偏好】不喝咖啡，只喝茶'])

    async def test_deleted_fact_id_cannot_be_restored_from_old_pending(self):
        await self.record()
        self.extraction()
        await self.distill()
        key = self.mod._key('qq:GroupMessage:A', '1')
        fid = self.bot._state['profiles'][key]['facts'][0]['id']
        await self.record()
        await collect(self.bot.cmd_forget_memory(Event('都忘掉 1 ' + fid)))
        self.assertTrue(await self.distill())
        self.assertEqual(self.bot._state['profiles'][key]['facts'], [])

    async def test_admin_edit_during_model_call_does_not_get_overwritten(self):
        await self.record()
        self.extraction()
        await self.distill()
        await self.record()
        release = self.context.provider.wait = asyncio.Event()
        task = asyncio.create_task(self.distill())
        await asyncio.sleep(0)
        await collect(self.bot.cmd_forget_memory(Event('都忘掉 1 全部')))
        release.set()
        self.assertFalse(await task)
        self.assertTrue(self.bot._pending)

    async def test_summary_is_single_merged_snapshot_and_rehydrated(self):
        self.bot._summaries['conv'] = '旧备忘'
        self.context.provider.result = '合并后的新备忘'
        original = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': [{'type': 'text', 'text': str(i)}]} for i in range(44)]
        req = NS(contexts=copy.deepcopy(original), conversation=NS(cid='conv'), extra_user_content_parts=[])
        await self.bot._rolling_summary(Event(), req)
        self.assertEqual(len(req.extra_user_content_parts), 1)
        self.assertNotIn('旧备忘', req.extra_user_content_parts[0].text)
        self.assertEqual(json.loads(self.context.provider.calls[0]['prompt'])['previous'], '旧备忘')
        second = NS(contexts=[], conversation=NS(cid='conv'), extra_user_content_parts=[])
        self.bot = self.new_bot()
        await self.bot._rolling_summary(Event(), second)
        self.assertIn('合并后的新备忘', second.extra_user_content_parts[0].text)

    async def test_failed_summary_preserves_full_history_and_old_snapshot(self):
        self.bot._summaries['conv'] = '旧备忘'
        self.context.provider.error = RuntimeError('offline')
        history = [{'role': 'user', 'content': '历史'} for _ in range(44)]
        req = NS(contexts=history, conversation=NS(cid='conv'), extra_user_content_parts=[])
        await self.bot._rolling_summary(Event(), req)
        self.assertIs(req.contexts, history)
        self.assertEqual(len(req.extra_user_content_parts), 1)

    async def test_tool_chain_is_left_to_core_compressor(self):
        history = [{'role': 'user', 'content': 'x'} for _ in range(44)] + [{'role': 'tool', 'content': 'result'}]
        req = NS(contexts=history, conversation=NS(cid='conv'), extra_user_content_parts=[])
        await self.bot._rolling_summary(Event(), req)
        self.assertIs(req.contexts, history)
        self.assertFalse(self.context.provider.calls)

    async def test_trim_keeps_all_unprocessed_events(self):
        self.mod.LINES_MAX = 2
        await self.record(5)
        self.bot._trim_events()
        self.assertEqual(len(self.new_bot()._pending), 5)

    async def test_partial_journal_tail_is_preserved_and_recovered(self):
        await self.record()
        with open(self.bot._events_path, 'ab') as f:
            f.write(b'{"seq":2')
        self.bot = self.new_bot()
        self.assertFalse(self.bot._blocked)
        await self.record()
        self.assertEqual(len(self.new_bot()._pending), 2)
        self.assertTrue(list(Path(self.temp.name).glob('*.partial-*')))

    async def test_corrupt_state_is_not_overwritten(self):
        path = Path(self.bot._state_path)
        path.write_text('{broken', encoding='utf-8')
        bot = self.new_bot()
        self.assertTrue(bot._blocked)
        await bot.observe(Event())
        self.assertEqual(path.read_text(encoding='utf-8'), '{broken')

    async def test_complete_invalid_tail_is_preserved_instead_of_truncated(self):
        await self.record()
        path = Path(self.bot._events_path)
        with path.open('ab') as f:
            f.write(b'{"seq":2,"text":"missing required metadata"}\n')
        before = path.read_bytes()
        self.assertTrue(self.new_bot()._blocked)
        self.assertEqual(path.read_bytes(), before)

    async def test_long_original_is_preserved_without_extracting_half_a_sentence(self):
        original = '我喜欢咖啡。' * 500 + '前面是转述，我本人不喜欢咖啡。'
        await self.record(text=original)
        self.assertEqual(self.new_bot()._pending[0]['text'], original)
        payload = self.bot._payload(self.bot._batch())
        self.assertTrue(payload['messages'][0]['extraction_skipped'])
        self.assertNotIn('我喜欢咖啡', json.dumps(payload, ensure_ascii=False))
        self.assertTrue(await self.distill())
        self.assertFalse(self.bot._state['profiles'])
        self.assertEqual(self.bot._state['audit'][-1]['operation'], 'skip_oversized')

    async def test_nested_corrupt_profile_is_not_accepted_as_healthy(self):
        state = copy.deepcopy(self.bot._state)
        state['profiles']['bad'] = {'facts': None}
        path = Path(self.bot._state_path)
        path.write_text(json.dumps(state), encoding='utf-8')
        before = path.read_bytes()
        self.assertTrue(self.new_bot()._blocked)
        self.assertEqual(path.read_bytes(), before)

    async def test_legacy_requires_explicit_binding_and_original_is_preserved(self):
        path = Path(self.temp.name) / 'profiles.json'
        path.write_text(json.dumps({'旧昵称': {'facts': ['【偏好】喜欢咖啡']}}, ensure_ascii=False), encoding='utf-8')
        Path(self.bot._state_path).unlink()
        self.bot = self.new_bot()
        self.assertFalse(self.bot._state['profiles'])
        await self.record()
        before = path.read_bytes()
        await collect(self.bot.cmd_claim_legacy(Event('都迁移记忆 1 旧昵称')))
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(self.bot._state['profiles'])


class VoiceAndConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_tts_cache_tracks_parameters_and_missing_files(self):
        mod = load_plugin('miyako_tts')
        calls = []
        class Response:
            status = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def read(self): return b'RIFF' + b'0' * 3000
        class Session:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def get(self, url, params):
                calls.append((url, params))
                return Response()
        with tempfile.TemporaryDirectory() as tmp:
            modules = {'astrbot.core.utils': NS(),
                'astrbot.core.utils.astrbot_path': NS(get_astrbot_temp_path=lambda: tmp),
                'astrbot.core.utils.datetime_utils': NS(generate_timestamp_id=lambda: str(len(calls)))}
            mod._GSV_CFG = {'api_base': 'http://fake', 'gsv_default_parms': {
                'gsv_ref_audio_path': 'C:/Voice/REF.wav', 'gsv_prompt_text': 'Hello Miyako'}}
            with patch.dict(sys.modules, modules), patch.object(mod.aiohttp, 'ClientSession', Session, create=True), \
                    patch.object(mod.aiohttp, 'ClientTimeout', lambda **kwargs: None, create=True):
                first = await mod._gsv_synth('こんにちは', None, None)
                self.assertEqual(first, await mod._gsv_synth('こんにちは', None, None))
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][1]['ref_audio_path'], 'C:/Voice/REF.wav')
                await mod._gsv_synth('こんにちは', '0.9', None)
                self.assertEqual(len(calls), 2)
                mod._GSV_CFG['gsv_default_parms']['gsv_prompt_text'] = 'Different prompt'
                changed = await mod._gsv_synth('こんにちは', None, None)
                self.assertEqual(len(calls), 3)
                Path(changed).unlink()
                await mod._gsv_synth('こんにちは', None, None)
                self.assertEqual(len(calls), 4)

    async def test_bootstrap_config_repair_backs_up_original_and_is_idempotent(self):
        spec = importlib.util.spec_from_file_location('setup_repro', ROOT / 'tools/setup_repro.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / 'cmd_config.json'
            original = '{"dashboard":{"password":"change_me","pbkdf2_password":""},"admins_id":["1"]}'
            cfg.write_text(original, encoding='utf-8')
            with patch.multiple(mod, DATA=tmp, CFG=str(cfg)):
                mod.setup_config()
                mod.setup_config()
            backups = list(Path(tmp).glob('*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding='utf-8'), original)
            self.assertEqual(json.loads(cfg.read_text(encoding='utf-8-sig'))['admins_id'], ['1'])

    async def test_bootstrap_repair_only_changes_known_invalid_credentials(self):
        spec = importlib.util.spec_from_file_location('setup_repro', ROOT / 'tools/setup_repro.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        broken = {'dashboard': {'password': 'change_me', 'pbkdf2_password': '', 'jwt_secret': 'existing-jwt'}}
        self.assertTrue(mod.repair_bootstrap_auth(broken))
        self.assertEqual(broken['dashboard']['password'], '')
        self.assertEqual(broken['dashboard']['jwt_secret'], 'existing-jwt')
        self.assertFalse(mod.repair_bootstrap_auth(broken))
        for dashboard in ({'password': 'md5-value'}, {'password': 'change_me', 'pbkdf2_password': 'valid-hash'}):
            conf = {'dashboard': dashboard}
            old = copy.deepcopy(conf)
            self.assertFalse(mod.repair_bootstrap_auth(conf))
            self.assertEqual(conf, old)

    async def test_disabled_voice_skips_prompt_and_fallback_translation(self):
        mod = load_plugin('miyako_tts')
        mod.VOICE_RATE = 0
        bot = object.__new__(mod.Main)
        event = Event()
        req = NS(extra_user_content_parts=[])
        await bot.ask_for_line(event, req)
        self.assertFalse(req.extra_user_content_parts)
        event._result = NS(chain=[Plain('中文')], is_llm_result=lambda: True)
        with patch.object(mod, '_fallback_translate', side_effect=AssertionError('must not translate')):
            await bot.attach_voice(event)
        self.assertFalse(event.get_extra('_miyako_voice_enabled'))

    async def test_voice_decision_is_reused_for_request_and_delivery(self):
        mod = load_plugin('miyako_tts')
        event = Event()
        with patch.object(mod.random, 'random', side_effect=[0.2, 0.9]) as random:
            mod.VOICE_RATE = 0.5
            self.assertTrue(mod._voice_enabled(event))
            self.assertTrue(mod._voice_enabled(event))
            self.assertEqual(random.call_count, 1)

    async def test_fresh_dashboard_allows_framework_password_generation(self):
        conf = json.loads((ROOT / 'local/AstrBot/data/cmd_config.repro.json').read_text(encoding='utf-8-sig'))
        dashboard = conf['dashboard']
        self.assertFalse(dashboard['password'])
        self.assertFalse(dashboard['pbkdf2_password'])
        self.assertFalse(dashboard['jwt_secret'])
        self.assertTrue(dashboard['password_change_required'])
        self.assertEqual(conf['platform_settings']['rate_limit']['count'], 0)


if __name__ == '__main__':
    unittest.main()
