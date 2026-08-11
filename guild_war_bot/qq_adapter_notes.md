# QQ 接入适配说明

当前项目已经把公会战逻辑封装在 `GuildWarBot.handle_message()` 里。后续无论使用 QQ 官方 SDK、Webhook、WebSocket，还是其他消息平台，只需要做三件事：

1. 从 QQ 消息事件里拿到发言人名称或绑定后的游戏名。
2. 把消息文本传给 `handle_message()`。
3. 如果返回内容不为空，把返回内容发回 QQ。

伪代码：

```python
from guild_war_bot.core import GuildWarBot

bot = GuildWarBot()

def on_qq_message(event):
    sender_name = resolve_game_name(event.sender_id, event.sender_nickname)
    text = event.content
    is_admin = event.sender_id in ADMIN_IDS

    reply = bot.handle_message(sender_name, text, is_admin=is_admin)
    if reply:
        send_qq_message(event.group_id, reply)
```

如果使用 QQ 官方群机器人，建议第一版让管理员在群内发送 `提醒未出刀`，机器人再被动回复。这样比定时主动推送更容易符合官方频率限制。

如果使用 QQ 小号挂机方案，推荐先走 NapCatQQ 的 OneBot 11 HTTP POST。项目里已经提供入口：

```powershell
python -m guild_war_bot.onebot_http
```

默认接收地址：

```text
http://127.0.0.1:8787/onebot
```

默认 NapCat HTTP API 地址：

```text
http://127.0.0.1:3000
```
