"""Minimal AstrBot boundary doubles. No network, service startup or production data."""
import importlib.util
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]


class At:
    def __init__(self, qq, name=""):
        self.qq, self.name = qq, name


class AtAll:
    pass


class Reply:
    def __init__(self, sender_id, id="quoted"):
        self.sender_id, self.id = sender_id, id


class TextPart:
    def __init__(self, text):
        self.text, self.temp = text, False
    def mark_as_temp(self):
        self.temp = True
        return self


class Plain:
    def __init__(self, text):
        self.text = text


class Record:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def decorator(*args, **kwargs):
    def apply(fn):
        fn.priority = kwargs.get("priority", 0)
        return fn
    return apply


def install_doubles():
    names = ["astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.platform",
             "astrbot.api.message_components", "astrbot.core", "astrbot.core.agent",
             "astrbot.core.agent.message", "astrbot.core.message", "astrbot.core.message.components",
             "astrbot.core.provider", "astrbot.core.provider.sources", "astrbot.core.provider.sources.gsv_selfhosted_source",
             "astrbot.core.provider.register", "astrbot.core.provider.entities"]
    for name in names:
        sys.modules.setdefault(name, types.ModuleType(name))
    api = sys.modules['astrbot.api']
    api.logger = logging.getLogger('test.plugins')
    api.star = NS(Star=object, Context=object)
    sys.modules['astrbot.api.event'].AstrMessageEvent = object
    sys.modules['astrbot.api.event'].filter = NS(
        platform_adapter_type=decorator, on_llm_request=decorator, on_llm_response=decorator,
        on_decorating_result=decorator, command=decorator, permission_type=decorator,
        PlatformAdapterType=NS(ALL='all'), PermissionType=NS(ADMIN='admin'))
    sys.modules['astrbot.api.platform'].MessageType = NS(GROUP_MESSAGE='group', FRIEND_MESSAGE='private')
    sys.modules['astrbot.core.agent.message'].TextPart = TextPart
    sys.modules['astrbot.api.message_components'].__dict__.update(At=At, AtAll=AtAll, Reply=Reply)
    sys.modules['astrbot.core.message.components'].__dict__.update(Plain=Plain, Record=Record)
    sys.modules['astrbot.core.provider.sources.gsv_selfhosted_source'].ProviderGSVTTS = object
    reg = sys.modules['astrbot.core.provider.register']
    reg.provider_cls_map, reg.provider_registry = {}, []
    reg.register_provider_adapter = decorator
    sys.modules['astrbot.core.provider.entities'].ProviderType = NS(TEXT_TO_SPEECH='tts')
    # TTS network boundary is never called in tests.
    sys.modules.setdefault('aiohttp', types.ModuleType('aiohttp'))


def load_plugin(name):
    install_doubles()
    path = ROOT / 'local/AstrBot/data/plugins' / name / 'main.py'
    spec = importlib.util.spec_from_file_location('tested_' + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Event:
    def __init__(self, text='你晚饭吃了吗', user='1', scope='qq:GroupMessage:A', parts=(), mid='m1', wake=False, kind='group'):
        self.message_str, self.user, self.unified_msg_origin = text, user, scope
        self.parts, self.is_at_or_wake_command, self.kind = list(parts), wake, kind
        self.message_obj = NS(message_id=mid)
        self.extras, self.stopped, self.call_llm, self._result = {}, False, False, None
    def get_message_type(self): return self.kind
    def get_sender_id(self): return self.user
    def get_self_id(self): return '99'
    def get_sender_name(self): return '同名群友'
    def get_group_id(self): return self.unified_msg_origin.rsplit(':', 1)[-1]
    def get_platform_id(self): return 'qq'
    def get_messages(self): return self.parts
    def get_extra(self, key, default=None): return self.extras.get(key, default)
    def set_extra(self, key, value): self.extras[key] = value
    def should_call_llm(self, value): self.call_llm = value
    def stop_event(self): self.stopped = True
    def is_stopped(self): return self.stopped
    def request_llm(self, **kwargs): return kwargs
    def plain_result(self, text): return text
    def get_result(self): return self._result


class Provider:
    def __init__(self, result='{"addressed_to":"public","action":"reply","score":8,"next_threshold":7}'):
        self.result, self.calls, self.error, self.wait = result, [], None, None
    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.wait:
            await self.wait.wait()
        if self.error:
            raise self.error
        result = self.result(kwargs) if callable(self.result) else self.result
        return NS(completion_text=result, usage=NS(input_other=20, input_cached=10, output=5))


class Context:
    def __init__(self, provider=None):
        self.provider = provider or Provider()
        self.selected = []
        self.conversation_manager = self
    async def get_using_provider_async(self, *args): return self.provider
    def get_provider_by_id(self, provider_id):
        self.selected.append(provider_id)
        return self.provider
    async def get_curr_conversation_id(self, scope): return 'conv'
    async def new_conversation(self, scope, platform_id): return 'new-conv'
    async def get_conversation(self, scope, cid): return NS(cid=cid)


async def collect(generator):
    return [item async for item in generator]
