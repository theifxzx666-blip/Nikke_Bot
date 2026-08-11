from __future__ import annotations

from dataclasses import dataclass

from .base import BotSkill, IncomingMessage, SkillContext
from .game_progress import GameProgressSkill
from .guild_war import guild_war_skills
from .nikke_wiki import NikkeWikiSkill


@dataclass(frozen=True)
class SkillDispatchResult:
    handled: bool
    reply: str | None = None


class SkillRegistry:
    def __init__(self, skills: list[BotSkill]) -> None:
        self.skills = skills

    def dispatch(self, message: IncomingMessage, context: SkillContext) -> SkillDispatchResult:
        for skill in self.skills:
            if not skill.matches(message):
                continue
            reply = skill.handle(message, context)
            return SkillDispatchResult(handled=True, reply=reply)
        return SkillDispatchResult(handled=False)


def default_registry() -> SkillRegistry:
    return SkillRegistry(
        [
            GameProgressSkill(),
            *guild_war_skills(),
            NikkeWikiSkill(),
        ]
    )
