import random

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("astrbot_plugin_quote", "YourName", "群精华消息金句随机抽取插件", "1.0.0")
class QuotePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def quote(self, event: AstrMessageEvent):
        """从群精华消息中随机roll一条金句发送"""
        # 只响应以"金句"开头的消息（不含斜杠）
        if not event.message_str.strip().startswith("金句"):
            return
        group_id = int(event.get_group_id())
        essence_data = await event.bot.get_essence_msg_list(group_id=group_id)

        if not essence_data:
            yield event.plain_result("这个群还没有精华消息哦～")
            event.stop_event()
            return

        picked = random.choice(essence_data)
        sender_nick = picked.get("sender_nick", "未知")
        sender_id = picked.get("sender_id", "未知")
        content_list = picked.get("content", [])

        # 提取精华消息的文本内容
        text_parts = []
        for item in content_list:
            if item.get("type") == "text":
                text = item.get("data", {}).get("text", "")
                if text:
                    text_parts.append(text)
            elif item.get("type") == "image":
                url = item.get("data", {}).get("url", "")
                if url:
                    text_parts.append(f"[图片: {url}]")
                else:
                    text_parts.append("[图片]")

        content_text = "".join(text_parts) if text_parts else "[非文本消息]"

        result = f"{sender_nick}({sender_id})曾曰：{content_text}"
        logger.info(f"金句插件 - roll到: {result}")
        yield event.plain_result(result)
        event.stop_event()

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
