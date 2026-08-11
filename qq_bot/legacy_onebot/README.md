# Legacy OneBot HTTP Entry

这里保留旧的 NapCat HTTP POST 直连本项目方案，作为 AstrBot 方案出问题时的回退入口。

新方案优先使用上一层目录的：

```text
01-install-env.bat
02-start-qq-bot.bat
```

不要让同一个 NapCat 账号同时把同一条群消息上报到 AstrBot 和这里的旧 HTTP 入口，否则会出现双回复。
