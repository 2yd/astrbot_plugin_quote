import asyncio
import importlib.util
import json
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    key: value['default']
    for key, value in json.loads((ROOT / '_conf_schema.json').read_text()).items()
}


class Plain:
    def __init__(self, text):
        self.text = text


class Image:
    def __init__(self, file):
        self.file = file

    @classmethod
    def fromURL(cls, url):
        if not url.startswith(('http://', 'https://')):
            raise ValueError('not a valid url')
        return cls(url)

    async def convert_to_base64(self):
        if self.file.endswith('/broken'):
            raise OSError('download failed')
        if self.file.endswith('/slow'):
            await asyncio.Future()
        return 'encoded-image'

    @classmethod
    def fromBase64(cls, value):
        return cls('base64://' + value)


def decorator(field):
    def factory(value):
        def decorate(function):
            setattr(function, field, value)
            return function
        return decorate
    return factory


# 替代宿主依赖，仅测试插件逻辑；不模拟真实协议端或发送网络。
api = ModuleType('astrbot.api')
api.AstrBotConfig = dict
api.logger = Mock()
event_api = ModuleType('astrbot.api.event')
event_api.AstrMessageEvent = object
event_api.filter = SimpleNamespace(
    PlatformAdapterType=SimpleNamespace(AIOCQHTTP='aiocqhttp'),
    EventMessageType=SimpleNamespace(GROUP_MESSAGE='group'),
    platform_adapter_type=decorator('platform_filter'),
    event_message_type=decorator('message_filter'),
)
components = ModuleType('astrbot.api.message_components')
components.Plain = Plain
components.Image = Image
star_api = ModuleType('astrbot.api.star')
star_api.Context = object
star_api.Star = type('Star', (), {'__init__': lambda self, context: None})
star_api.register = lambda *args: lambda cls: cls
spec = importlib.util.spec_from_file_location('quote_under_test', ROOT / 'main.py')
plugin_module = importlib.util.module_from_spec(spec)
with patch.dict('sys.modules', {
    'astrbot': ModuleType('astrbot'), 'astrbot.api': api,
    'astrbot.api.event': event_api, 'astrbot.api.star': star_api,
    'astrbot.api.message_components': components,
}):
    spec.loader.exec_module(plugin_module)


class Bot:
    def __init__(self, messages=None, error=None, slow=False):
        self.messages = messages if messages is not None else [quote()]
        self.error = error
        self.slow = slow
        self.calls = 0

    async def get_essence_msg_list(self, **kwargs):
        self.calls += 1
        if self.slow:
            await asyncio.Future()
        if self.error:
            raise self.error
        return self.messages


def quote(nick='小明', content=None):
    return {
        'sender_nick': nick, 'sender_id': 42, 'message_id': 7,
        'content': content if content is not None else [
            {'type': 'text', 'data': {'text': '金句内容'}},
        ],
    }


def text(value):
    return {'type': 'text', 'data': {'text': value}}


def image(url=None):
    return {'type': 'image', 'data': {'url': url}}


class Event:
    def __init__(self, bot, message='金句', group='123', platform='qq-1', account='456'):
        self.bot = bot
        self.message_str = message
        self.group = group
        self.platform = platform
        self.account = account
        self.stopped = False

    def get_group_id(self): return self.group
    def get_platform_id(self): return self.platform
    def get_self_id(self): return self.account
    def stop_event(self): self.stopped = True
    def plain_result(self, value): return [Plain(value)]
    def chain_result(self, value): return value


async def invoke(plugin, event):
    return [value async for value in plugin.quote(event)]


class QuoteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = dict(DEFAULTS)
        self.plugin = plugin_module.QuotePlugin(None, self.config)
        api.logger.reset_mock()

    async def test_exact_commands(self):
        for command in ['金句', '/金句', ' \t/金句\n']:
            event = Event(Bot(), command)
            self.assertEqual(len(await invoke(self.plugin, event)), 1)
            self.assertTrue(event.stopped)
        for command in ['金句xxx', '/金句xxx', '金句 参数', '一句金句', '']:
            bot = Bot()
            event = Event(bot, command)
            self.assertEqual(await invoke(self.plugin, event), [])
            self.assertEqual(bot.calls, 0)
            self.assertFalse(event.stopped)

    async def test_platform_and_group_filters(self):
        self.assertEqual(self.plugin.quote.platform_filter, 'aiocqhttp')
        self.assertEqual(self.plugin.quote.message_filter, 'group')

    async def test_batch_command_forms(self):
        messages = [quote(f'群友{i}', [text(f'内容{i}')]) for i in range(10)]
        bot = Bot(messages)
        for command in ['金句10', '/金句10', '金句 10', '/金句 10', ' \t/金句 10\n']:
            event = Event(bot, command)
            result = await invoke(self.plugin, event)
            self.assertEqual(len(result), 1)
            rendered = ''.join(part.text for part in result[0])
            self.assertEqual(set(rendered.splitlines()), {
                f'群友{i}(42)曾曰：内容{i}' for i in range(10)
            })
            self.assertEqual(len(rendered.splitlines()), 10)
            self.assertTrue(event.stopped)
        self.assertEqual(bot.calls, 1)

    async def test_malformed_batch_commands_ignored(self):
        for command in ['金句10abc', '/金句 10条', '金句 1.5', '金句 1 2',
                        '金句+2', '金句 2\n3', '金句1e2']:
            bot = Bot()
            event = Event(bot, command)
            self.assertEqual(await invoke(self.plugin, event), [])
            self.assertEqual(bot.calls, 0)
            self.assertFalse(event.stopped)

    async def test_invalid_count_config_and_no_fetch(self):
        self.config['max_quotes'] = 5
        self.config['invalid_count_message'] = '最多 {max_count} 条 {literal}'
        for command in ['金句0', '/金句 -1', '金句6', '金句' + '9' * 5000]:
            bot = Bot()
            event = Event(bot, command)
            result = await invoke(self.plugin, event)
            self.assertEqual(result[0][0].text, '最多 5 条 {literal}')
            self.assertEqual(bot.calls, 0)
            self.assertTrue(event.stopped)

    async def test_configurable_limit(self):
        self.config['max_quotes'] = 25
        messages = [quote(str(i)) for i in range(25)]
        result = await invoke(self.plugin, Event(Bot(messages), '金句25'))
        self.assertEqual(len(result), 1)
        self.assertEqual(len(''.join(part.text for part in result[0]).splitlines()), 25)
        self.config['max_quotes'] = 0
        event = Event(Bot(), '金句2')
        result = await invoke(self.plugin, event)
        self.assertIn('1～1', result[0][0].text)
        self.assertEqual(event.bot.calls, 0)

    async def test_insufficient_essence_sends_all_once(self):
        self.config['insufficient_message'] = '目前有 {available} 条'
        messages = [quote('甲'), quote('乙'), quote('丙')]
        event = Event(Bot(messages), '金句10')
        result = await invoke(self.plugin, event)
        self.assertEqual(len(result), 1)
        lines = ''.join(part.text for part in result[0]).splitlines()
        self.assertEqual(lines[0], '目前有 3 条')
        self.assertEqual(len(lines), 4)
        self.assertEqual(set(lines[1:]),
                         {'甲(42)曾曰：金句内容', '乙(42)曾曰：金句内容', '丙(42)曾曰：金句内容'})
        self.assertTrue(event.stopped)

    async def test_batch_empty_and_failure(self):
        for bot, expected in [(Bot([]), self.config['empty_message']),
                              (Bot(error=OSError('offline')), self.config['error_message'])]:
            event = Event(bot, '金句10')
            result = await invoke(self.plugin, event)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0][0].text, expected)
            self.assertTrue(event.stopped)

    async def test_batch_stops_after_single_merged_reply(self):
        event = Event(Bot([quote('甲'), quote('乙'), quote('丙')]), '金句3')
        handler = self.plugin.quote(event)
        await anext(handler)
        self.assertFalse(event.stopped)
        with self.assertRaises(StopAsyncIteration):
            await anext(handler)
        self.assertTrue(event.stopped)
        self.assertEqual(event.bot.calls, 1)

    async def test_batch_image_failure_does_not_interrupt_following_quotes(self):
        messages = [quote('甲'), quote('乙', [image('invalid'), text('保留文字')]),
                    quote('丙', [image('https://example.com/good')])]
        with patch.object(plugin_module.random, 'sample', return_value=messages):
            result = await invoke(self.plugin, Event(Bot(messages), '金句3'))
        self.assertEqual(len(result), 1)
        rendered = ''.join(part.text for part in result[0] if isinstance(part, Plain))
        self.assertEqual(rendered, '甲(42)曾曰：金句内容\n乙(42)曾曰：保留文字\n丙(42)曾曰：')
        self.assertEqual(result[0][-1].file, 'base64://encoded-image')

    async def test_line_break_after_image_is_not_standalone_whitespace(self):
        messages = [quote('甲', [image('https://example.com/good')]), quote('乙')]
        with patch.object(plugin_module.random, 'sample', return_value=messages):
            result = await invoke(self.plugin, Event(Bot(messages), '金句2'))
        self.assertEqual(len(result), 1)
        chain = result[0]
        self.assertIsInstance(chain[1], Image)
        self.assertEqual(chain[2].text, '\n乙(42)曾曰：')
        self.assertTrue(all(part.text.strip() for part in chain if isinstance(part, Plain)))

    async def test_stop_event_after_reply_is_dispatched(self):
        # 宿主在 yield 时执行发送阶段；提前 stop 会让调度器跳过回复。
        self.config['cache_ttl_seconds'] = 0
        for bot in [Bot(), Bot([]), Bot(error=OSError('offline'))]:
            event = Event(bot)
            handler = self.plugin.quote(event)
            await anext(handler)
            self.assertFalse(event.stopped)
            with self.assertRaises(StopAsyncIteration):
                await anext(handler)
            self.assertTrue(event.stopped)

    async def test_configurable_failure_and_retry(self):
        self.config['error_message'] = '自定义失败提示'
        bot = Bot(error=OSError('offline'))
        event = Event(bot)
        result = await invoke(self.plugin, event)
        self.assertEqual(result[0][0].text, '自定义失败提示')
        self.assertTrue(event.stopped)
        self.assertFalse(self.plugin._essence_cache)
        bot.error = None
        self.assertEqual(len(await invoke(self.plugin, Event(bot))), 1)
        self.assertEqual(bot.calls, 2)

    async def test_api_timeout(self):
        self.config['request_timeout_seconds'] = 1
        self.config['error_message'] = '请求超时'
        result = await invoke(self.plugin, Event(Bot(slow=True)))
        self.assertEqual(result[0][0].text, '请求超时')
        self.assertFalse(self.plugin._essence_cache)

    async def test_empty_list_not_cached(self):
        self.config['empty_message'] = '暂时没有'
        bot = Bot([])
        result = await invoke(self.plugin, Event(bot))
        self.assertEqual(result[0][0].text, '暂时没有')
        bot.messages = [quote()]
        self.assertEqual(len((await invoke(self.plugin, Event(bot)))[0]), 2)
        self.assertEqual(bot.calls, 2)

    async def test_blank_nickname_default_and_config(self):
        for nick in [None, '', ' \t\n']:
            self.config['cache_ttl_seconds'] = 0
            result = await invoke(self.plugin, Event(Bot([quote(nick)])))
            self.assertEqual(result[0][0].text, '某已退群群友(42)曾曰：')
        self.config['fallback_nickname'] = '自定义群友'
        result = await invoke(self.plugin, Event(Bot([quote('')])))
        self.assertEqual(result[0][0].text, '自定义群友(42)曾曰：')

    async def test_image_failure_preserves_text_and_other_images(self):
        content = [text('前'), image('invalid'), image('https://example.com/broken'),
                   image(), image('https://example.com/good'), text('后')]
        result = (await invoke(self.plugin, Event(Bot([quote(content=content)]))))[0]
        self.assertEqual([part.text for part in result if isinstance(part, Plain)],
                         ['小明(42)曾曰：', '前', '后'])
        self.assertEqual([part.file for part in result if isinstance(part, Image)],
                         ['base64://encoded-image'])
        self.assertIsInstance(result[2], Image)
        self.assertEqual(api.logger.warning.call_count, 2)
        api.logger.info.assert_not_called()

    async def test_image_timeout(self):
        self.config['image_timeout_seconds'] = 1
        result = await self.plugin._build_content_chain(
            [image('https://example.com/slow'), text('还在')], 123)
        self.assertEqual([part.text for part in result], ['还在'])

    async def test_only_failed_images_no_placeholder(self):
        result = await invoke(self.plugin, Event(Bot([
            quote(content=[image('invalid'), image()]),
        ])))
        self.assertEqual([part.text for part in result[0]], ['小明(42)曾曰：'])

    async def test_non_text_message_config(self):
        self.config['non_text_message'] = '暂不支持的内容'
        result = await self.plugin._build_content_chain([], 123)
        self.assertEqual(result[0].text, '暂不支持的内容')

    async def test_cache_hit_expiry_and_fresh_random_pick(self):
        bot = Bot([quote('甲'), quote('乙')])
        with patch.object(plugin_module, 'monotonic', return_value=100) as clock:
            with patch.object(plugin_module.random, 'choice', side_effect=bot.messages) as choose:
                first = await invoke(self.plugin, Event(bot))
                second = await invoke(self.plugin, Event(bot))
            self.assertEqual(bot.calls, 1)
            self.assertEqual(choose.call_count, 2)
            self.assertTrue(first[0][0].text.startswith('甲'))
            self.assertTrue(second[0][0].text.startswith('乙'))
            clock.return_value = 130
            await invoke(self.plugin, Event(bot))
            self.assertEqual(bot.calls, 2)

    async def test_cache_disabled(self):
        self.config['cache_ttl_seconds'] = 0
        bot = Bot()
        await invoke(self.plugin, Event(bot))
        await invoke(self.plugin, Event(bot))
        self.assertEqual(bot.calls, 2)
        self.assertFalse(self.plugin._essence_cache)

    async def test_cache_isolation(self):
        bot = Bot()
        for group, platform, account in [
            ('123', 'qq-1', '456'), ('789', 'qq-1', '456'),
            ('123', 'qq-2', '456'), ('123', 'qq-1', '999'),
        ]:
            await invoke(self.plugin, Event(bot, group=group, platform=platform, account=account))
        self.assertEqual(bot.calls, 4)
        self.assertEqual(len(self.plugin._essence_cache), 4)

    async def test_cache_bound_and_terminate(self):
        self.plugin.MAX_CACHED_GROUPS = 2
        bot = Bot()
        for group in ['1', '2', '1', '3']:
            await invoke(self.plugin, Event(bot, group=group))
        self.assertEqual(len(self.plugin._essence_cache), 2)
        self.assertEqual({key[2] for key in self.plugin._essence_cache}, {1, 3})
        await self.plugin.terminate()
        self.assertFalse(self.plugin._essence_cache)


if __name__ == '__main__':
    unittest.main()
