from __future__ import annotations

from typing import ClassVar

from guild_war_bot.core import (
    NO_ATTACK_COMMAND,
    help_text,
    normalize_command,
    parse_attack_command,
    parse_attack_index,
    parse_damage,
    raid_status_text,
)

from .base import IncomingMessage, SkillContext


def command_content(message: IncomingMessage) -> str:
    return normalize_command(message.raw_text or message.command)


class GuildWarHelpSkill:
    name: str = "guild_war_help"
    commands: ClassVar[set[str]] = {"帮助", "菜单", "指令", "help"}

    def matches(self, message: IncomingMessage) -> bool:
        return command_content(message) in self.commands

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        return help_text()


class GuildWarAttackStatusSkill:
    name: str = "guild_war_attack_status"
    commands: ClassVar[set[str]] = {"查刀", "进度", "统计"}
    prefixes: ClassVar[tuple[str, ...]] = ("查刀 ", "查询 ", "查成员 ")

    def matches(self, message: IncomingMessage) -> bool:
        content = command_content(message)
        return content in self.commands or content.startswith(self.prefixes)

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        content = command_content(message)
        for prefix in self.prefixes:
            if content.startswith(prefix):
                return context.bot.member_report(content[len(prefix) :])
        return context.bot.summary()


class GuildWarReminderSkill:
    name: str = "guild_war_reminder"
    commands: ClassVar[set[str]] = {"未出刀", "提醒未出刀", "提醒", "催刀", "催一下", "催0刀"}

    def matches(self, message: IncomingMessage) -> bool:
        return command_content(message) in self.commands

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        content = command_content(message)
        if content in {"催刀", "催一下", "催0刀"}:
            return context.bot.urge_zero_attack_text()
        return context.bot.remind_text()


class GuildWarRaidTimeSkill:
    name: str = "guild_war_raid_time"
    commands: ClassVar[set[str]] = {"会战时间", "突袭时间", "活动时间"}

    def matches(self, message: IncomingMessage) -> bool:
        return command_content(message) in self.commands

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        return raid_status_text()


class GuildWarDailyReportSkill:
    name: str = "guild_war_daily_report"
    commands: ClassVar[set[str]] = {"日报", "结算"}

    def matches(self, message: IncomingMessage) -> bool:
        return command_content(message) in self.commands

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        return context.bot.daily_report()


class GuildWarDamageReportSkill:
    name: str = "guild_war_damage_report"
    commands: ClassVar[set[str]] = {"伤害", "伤害统计", "伤害榜", "排行", "伤害概览", "伤害汇总"}

    def matches(self, message: IncomingMessage) -> bool:
        return command_content(message) in self.commands

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        content = command_content(message)
        if content in {"伤害概览", "伤害汇总"}:
            return context.bot.damage_summary()
        return context.bot.damage_ranking()


class GuildWarMemberListSkill:
    name: str = "guild_war_member_list"
    commands: ClassVar[set[str]] = {"成员", "名单"}

    def matches(self, message: IncomingMessage) -> bool:
        return command_content(message) in self.commands

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        members = context.bot.list_members()
        if not members:
            return "成员名单为空。"
        return "成员名单：\n" + "\n".join(f"- {name}" for name in members)


class GuildWarAttackRecordSkill:
    name: str = "guild_war_attack_record"
    commands: ClassVar[set[str]] = {"出刀"}

    def matches(self, message: IncomingMessage) -> bool:
        content = command_content(message)
        return content == "出刀" or content.startswith("出刀 ")

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        attack = parse_attack_command(command_content(message))
        if attack is NO_ATTACK_COMMAND:
            return None
        damage, note = attack
        member_name = context.bot.resolve_member_name(
            message.sender_name,
            message.sender_qq or None,
        )
        return context.bot.record_attack(member_name, damage=damage, note=note)


class GuildWarAdminSkill:
    name: str = "guild_war_admin"
    commands: ClassVar[set[str]] = {"重置今日", "清空今日", "重置"}
    prefixes: ClassVar[tuple[str, ...]] = ("代出刀 ", "改伤害 ")

    def matches(self, message: IncomingMessage) -> bool:
        content = command_content(message)
        return content in self.commands or content.startswith(self.prefixes)

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        if not message.is_admin:
            return "只有管理员可以使用这条指令。"

        content = command_content(message)
        if content in self.commands:
            return context.bot.reset_day()

        if content.startswith("代出刀 "):
            parts = content.split(maxsplit=2)
            if len(parts) < 2:
                return "格式：代出刀 成员名 [伤害]"
            damage = parse_damage(parts[2]) if len(parts) > 2 else None
            return context.bot.record_attack(parts[1], damage=damage)

        if content.startswith("改伤害 "):
            parts = content.split()
            if len(parts) < 3:
                return "格式：改伤害 成员名 1200w [第几刀]"
            damage = parse_damage(parts[2])
            if damage is None:
                return "伤害格式不正确，例如：1200w、3500万、12500000。"
            attack_index = parse_attack_index(parts[3]) if len(parts) > 3 else None
            if len(parts) > 3 and attack_index is None:
                return "第几刀格式不正确，例如：1、2、3、第2刀。"
            return context.bot.update_attack_damage(parts[1], damage, attack_index)

        return None


def guild_war_skills() -> list[object]:
    return [
        GuildWarHelpSkill(),
        GuildWarAttackStatusSkill(),
        GuildWarReminderSkill(),
        GuildWarRaidTimeSkill(),
        GuildWarDailyReportSkill(),
        GuildWarDamageReportSkill(),
        GuildWarMemberListSkill(),
        GuildWarAttackRecordSkill(),
        GuildWarAdminSkill(),
    ]
