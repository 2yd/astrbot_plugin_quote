# 随机金句

AstrBot 群精华消息插件：随机抽取当前群的一条或多条精华消息，发送作者信息及图文内容。

## 使用条件与安装

- 使用 AstrBot 的 OneBot v11（aiocqhttp）适配器连接 QQ 协议端。
- 协议端需要支持 `get_essence_msg_list`，并返回包含 `content` 消息段数组的精华列表，例如 NapCat 的数组消息格式。
- 在 AstrBot 插件管理中通过仓库地址 `https://github.com/2yd/astrbot_plugin_quote` 安装，或将插件目录放入 `data/plugins/astrbot_plugin_quote` 后加载。
- 无额外第三方依赖，所需接口由 AstrBot 提供。

## 使用方法

| 指令 | 行为 |
| --- | --- |
| `金句`、`/金句` | 随机抽取 1 条 |
| `金句10`、`/金句10` | 随机抽取 10 条 |
| `金句 10`、`/金句 10` | 同样抽取 10 条，推荐使用空格分隔数量 |

允许前后空白。数量只支持整数，`金句xxx`、`金句10abc`、`金句 1.5` 等消息不会触发。私聊和其他平台不会触发。

单次默认最多抽取 20 条，数量为 0、负数或超过上限时回复数量提示。一次抽取内不重复；多条金句合并成一条图文消息，以换行分隔，不添加序号。如果精华不足，现有数量的提示放在同一条消息的开头，然后列出全部精华。不同请求之间可能再次抽到同一条。

回复示例：

```text
小明(123456)曾曰：今天也是美好的一天。
```

文字和图片保持原始顺序。作者昵称缺失、为空或只有空白时，默认显示「某已退群群友」。

图片会在发送前处理；地址缺失、无效、读取失败或超时的图片直接省略，不发送图片占位文案，其余文字和成功处理的图片继续发送。若原消息只有图片且全部处理失败，则只发送作者前缀。当前仅展示文字和图片，其他类型的消息段会被忽略。

## 配置

在 AstrBot 插件管理中打开本插件的配置，修改并保存。配置通过 `_conf_schema.json` 声明，由 AstrBot 自动创建和加载。

| 配置项 | 默认值 | 作用 |
| --- | --- | --- |
| `max_quotes` | 20 | 单次抽取上限，最少为 1 |
| `invalid_count_message` | 抽取数量请填写 1～{max_count}，例如：金句10 | 数量超出范围时的回复，支持 `{max_count}` 占位符 |
| `insufficient_message` | 群里只有 {available} 条精华，本次全部发送～ | 精华不足时的回复，支持 `{available}` 占位符 |
| `error_message` | 获取精华消息失败，请稍后重试～ | 接口异常或超时时的回复 |
| `empty_message` | 这个群还没有精华消息哦～ | 精华列表为空时的回复 |
| `fallback_nickname` | 某已退群群友 | 空昵称的兜底值 |
| `non_text_message` | [非文本消息] | 没有可展示内容时的提示，图片处理失败不显示此提示 |
| `cache_ttl_seconds` | 30 | 列表缓存时间，设为 0 关闭 |
| `request_timeout_seconds` | 15 | 获取列表的超时时间，最少 1 秒 |
| `image_timeout_seconds` | 10 | 单张图片处理的超时时间，最少 1 秒 |

缓存按平台实例、机器人账号和群隔离，最多保存 128 份列表，卸载时清空。每次请求都重新随机抽取，不缓存抽取结果或图片；空列表和失败请求不缓存。新增或删除精华消息可能在缓存到期后才体现。

抽取记录和缓存命中使用 DEBUG 日志，只记录群号和消息 ID；接口异常记录错误，图片处理失败记录警告。

## 开发资料

本地逻辑测试（使用模拟宿主接口，不连接 QQ）：

```sh
python3 -m unittest discover -s tests -v
```

- [AstrBot 插件配置](https://docs.astrbot.app/dev/star/guides/plugin-config.html)
- [AstrBot 消息发送](https://docs.astrbot.app/dev/star/guides/send-message.html)
- [AstrBot 消息事件与平台过滤](https://docs.astrbot.app/dev/star/guides/listen-message-event.html)
