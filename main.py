import asyncio
import random
import re
from collections import OrderedDict
from time import monotonic

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register


@register("astrbot_plugin_quote", "2yd", "群精华消息金句随机抽取插件", "1.2.1")
class QuotePlugin(Star):
    MAX_CACHED_GROUPS = 128

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._essence_cache = OrderedDict()

    async def _get_essence_messages(self, event: AstrMessageEvent, group_id: int):
        ttl = max(0, self.config.get("cache_ttl_seconds", 30))
        cache_key = (event.get_platform_id(), event.get_self_id(), group_id)
        now = monotonic()

        # 只缓存成功获取的列表，按平台实例、机器人账号和群隔离。
        for key, (fetched_at, _) in list(self._essence_cache.items()):
            if now - fetched_at >= ttl:
                del self._essence_cache[key]
        cached = self._essence_cache.get(cache_key)
        if cached is not None:
            self._essence_cache.move_to_end(cache_key)
            logger.debug(f"金句插件 - 命中群 {group_id} 的精华列表缓存")
            return cached[1]

        messages = await asyncio.wait_for(
            event.bot.get_essence_msg_list(group_id=group_id),
            timeout=max(1, self.config.get("request_timeout_seconds", 15)),
        )
        if ttl > 0 and messages:
            self._essence_cache[cache_key] = (monotonic(), messages)
            self._essence_cache.move_to_end(cache_key)
            while len(self._essence_cache) > self.MAX_CACHED_GROUPS:
                self._essence_cache.popitem(last=False)
        return messages

    async def _build_content_chain(self, content_list, group_id: int):
        content_chain = []
        has_image = False
        for item in content_list:
            if item.get("type") == "text":
                text = item.get("data", {}).get("text", "")
                if text:
                    content_chain.append(Plain(text))
            elif item.get("type") == "image":
                has_image = True
                url = item.get("data", {}).get("url", "")
                if not url:
                    continue
                try:
                    # 提前读取图片，避免发送整条消息时因下载失败而丢失文字。
                    image = Image.fromURL(url)
                    image_base64 = await asyncio.wait_for(
                        image.convert_to_base64(),
                        timeout=max(1, self.config.get("image_timeout_seconds", 10)),
                    )
                    content_chain.append(Image.fromBase64(image_base64))
                except Exception as exc:
                    logger.warning(
                        f"金句插件 - 群 {group_id} 的图片处理失败，已跳过 "
                        f"({type(exc).__name__})"
                    )

        # 图片失败只省略图片，不把它误标成非文本消息。
        if not content_chain and not has_image:
            content_chain.append(
                Plain(self.config.get("non_text_message", "[非文本消息]"))
            )
        return content_chain

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def quote(self, event: AstrMessageEvent):
        """随机抽取金句，可使用「金句10」或「/金句 10」指定数量。"""
        match = re.fullmatch(r"/?金句(?:[ \t]*(-?[0-9]+))?", event.message_str.strip())
        if match is None:
            return

        max_count = max(1, self.config.get("max_quotes", 20))
        try:
            count = int(match.group(1) or "1")
        except ValueError:
            # 超长数字超过 Python 的整数转换限制时，也按无效数量处理。
            count = 0
        if not 1 <= count <= max_count:
            message = self.config.get(
                "invalid_count_message", "抽取数量请填写 1～{max_count}，例如：金句10"
            ).replace("{max_count}", str(max_count))
            yield event.plain_result(message)
            event.stop_event()
            return

        try:
            group_id = int(event.get_group_id())
            essence_data = await self._get_essence_messages(event, group_id)
        except Exception:
            logger.exception(f"金句插件 - 获取群 {event.get_group_id()} 的精华消息失败")
            yield event.plain_result(
                self.config.get("error_message", "获取精华消息失败，请稍后重试～")
            )
            event.stop_event()
            return

        if not essence_data:
            yield event.plain_result(
                self.config.get("empty_message", "这个群还没有精华消息哦～")
            )
            event.stop_event()
            return

        actual_count = min(count, len(essence_data))
        selected = (
            [random.choice(essence_data)]
            if count == 1
            else random.sample(essence_data, actual_count)
        )
        result_chain = []
        if actual_count < count:
            message = self.config.get(
                "insufficient_message", "群里只有 {available} 条精华，本次全部发送～"
            ).replace("{available}", str(actual_count))
            result_chain.append(Plain(message))

        for picked in selected:
            sender_nick = (picked.get("sender_nick") or "").strip() or self.config.get(
                "fallback_nickname", "某已退群群友"
            )
            sender_id = picked.get("sender_id", "未知")
            content_chain = await self._build_content_chain(
                picked.get("content", []), group_id
            )
            logger.debug(
                f"金句插件 - 群 {group_id} 抽取精华消息 {picked.get('message_id', '未知')}"
            )
            prefix = f"{sender_nick}({sender_id})曾曰："
            if result_chain:
                # 不单独发送纯换行组件，避免适配器忽略空白文本段。
                if isinstance(result_chain[-1], Plain):
                    prefix = result_chain.pop().text + "\n" + prefix
                else:
                    prefix = "\n" + prefix
            result_chain.extend([Plain(prefix), *content_chain])

        yield event.chain_result(result_chain)
        event.stop_event()

    async def terminate(self):
        self._essence_cache.clear()
