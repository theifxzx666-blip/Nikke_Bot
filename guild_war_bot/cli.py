from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import GuildWarBot, db_path_from_env, help_text, now_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m guild_war_bot",
        description="本地公会战统计机器人",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="初始化数据库")

    add_member = sub.add_parser("add-member", help="添加成员")
    add_member.add_argument("name")
    add_member.add_argument("--qq", default=None)

    import_members = sub.add_parser("import-members", help="从 CSV 导入成员")
    import_members.add_argument("csv_path")

    sub.add_parser("cli", help="进入本地聊天模拟")
    sub.add_parser("report", help="查看今日统计")
    sub.add_parser("remind", help="生成提醒文案")
    sub.add_parser("reset", help="重置今日出刀记录")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    bot = GuildWarBot()
    try:
        if args.command == "init":
            print(f"数据库已初始化：{db_path_from_env()}")
            return 0
        if args.command == "add-member":
            print(bot.add_member(args.name, args.qq))
            return 0
        if args.command == "import-members":
            print(bot.import_members(Path(args.csv_path)))
            return 0
        if args.command == "cli":
            run_interactive(bot)
            return 0
        if args.command == "report":
            print(bot.summary())
            return 0
        if args.command == "remind":
            print(bot.remind_text())
            return 0
        if args.command == "reset":
            print(bot.reset_day())
            return 0
    finally:
        bot.close()

    parser.print_help()
    return 1


def run_interactive(bot: GuildWarBot) -> None:
    print("本地公会战机器人已启动。输入 `admin: 帮助` 查看指令，输入 `exit` 退出。")
    print(f"数据库：{bot.db_path}")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if raw.lower() in {"exit", "quit", "q"}:
            return
        if not raw:
            continue

        sender, text, is_admin = parse_local_line(raw)
        if not sender or not text:
            print("格式示例：张三: 出刀 1200w")
            continue

        reply = bot.handle_message(sender, text, is_admin=is_admin)
        if reply is None:
            print("机器人：没识别这条指令。输入 `admin: 帮助` 查看可用指令。")
        else:
            print(f"机器人 [{now_text()}]:")
            print(reply)


def parse_local_line(raw: str) -> tuple[str, str, bool]:
    if ":" in raw:
        sender, text = raw.split(":", 1)
    elif "：" in raw:
        sender, text = raw.split("：", 1)
    else:
        return "", "", False
    sender = sender.strip()
    text = text.strip()
    is_admin = sender.lower() in {"admin", "管理员", "群主"}
    return sender, text, is_admin


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
