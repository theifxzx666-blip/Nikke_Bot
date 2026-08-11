from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import aiohttp
from astrbot.api import AstrBotConfig
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


DEFAULT_BRIDGE_URL = "http://127.0.0.1:8793"
POLL_INTERVAL_SECONDS = 2
POLL_ATTEMPTS = 60
REQUEST_TIMEOUT_SECONDS = 10

COMMAND_ALIASES = {
    "帮助",
    "菜单",
    "指令",
    "help",
    "进度",
    "统计",
    "出刀",
    "未出刀",
    "提醒未出刀",
    "提醒",
    "催刀",
    "催一下",
    "催0刀",
    "日报",
    "结算",
    "伤害",
    "伤害统计",
    "伤害榜",
    "排行",
    "伤害概览",
    "伤害汇总",
    "会战时间",
    "突袭时间",
    "活动时间",
    "会战进度查询",
    "会战进度",
    "联盟突袭进度查询",
    "成员",
    "名单",
    "重置今日",
    "清空今日",
    "重置",
    "代出刀",
    "改伤害",
    "角色",
    "查角色",
    "角色卡",
    "是谁",
    "wiki",
    "查",
}


class NikkeGuildBridgePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.bridge_url = self._get_string(
            ("bridge", "bridge_url"),
            os.environ.get("NIKKE_GUILD_BRIDGE_URL", DEFAULT_BRIDGE_URL),
        ).rstrip("/")
        self.request_timeout_seconds = self._get_int(
            ("bridge", "request_timeout_seconds"),
            REQUEST_TIMEOUT_SECONDS,
        )
        self.poll_interval_seconds = self._get_int(
            ("bridge", "outbox_poll_interval_seconds"),
            POLL_INTERVAL_SECONDS,
        )
        self.poll_attempts = self._get_int(
            ("bridge", "outbox_poll_attempts"),
            POLL_ATTEMPTS,
        )

    @filter.command("查刀", alias=COMMAND_ALIASES)
    async def guild_command(self, event: AstrMessageEvent):
        """转发 NIKKE 公会战指令到本地桥接服务。"""
        text = event.message_str.strip()
        if not text:
            return

        try:
            result = await self._post_command(event, text)
        except Exception as exc:
            logger.error(f"NIKKE bridge command failed: {type(exc).__name__}: {exc}")
            yield event.plain_result(f"会战桥接服务不可用：{exc}")
            return

        reply = result.get("reply")
        if reply:
            yield event.plain_result(str(reply))

        if not self._may_have_async_outputs(text, reply):
            return

        session_id = str(result.get("session_id") or "")
        after = 0
        for _ in range(self.poll_attempts):
            await asyncio.sleep(self.poll_interval_seconds)
            try:
                outbox = await self._get_outbox(session_id, after)
            except Exception as exc:
                logger.error(f"NIKKE bridge outbox poll failed: {type(exc).__name__}: {exc}")
                return

            after = int(outbox.get("next_after") or after)
            messages = outbox.get("messages") or []
            if not messages:
                continue
            for message in messages:
                if message.get("type") == "text" and message.get("text"):
                    yield event.plain_result(str(message["text"]))
                elif message.get("type") == "image" and message.get("path"):
                    caption = str(message.get("caption") or "")
                    if caption:
                        yield event.plain_result(caption)
                    yield event.image_result(str(message["path"]))

    async def _post_command(self, event: AstrMessageEvent, text: str) -> dict[str, Any]:
        payload = {
            "text": text,
            "sender_name": event.get_sender_name(),
            "sender_qq": event.get_sender_id(),
            "is_admin": self._is_admin(event),
            "session_id": self._session_id(event),
        }
        return await self._request_json("POST", "/command", payload)

    async def _get_outbox(self, session_id: str, after: int) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            "/outbox",
            None,
            params={"session_id": session_id, "after": str(after)},
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method,
                f"{self.bridge_url}{path}",
                json=payload,
                params=params,
                headers={"Accept": "application/json"},
            ) as response:
                response.raise_for_status()
                raw = await response.text(encoding="utf-8")
        data = json.loads(raw)
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "bridge returned ok=false")
        return data

    def _session_id(self, event: AstrMessageEvent) -> str:
        group_id = event.get_group_id() or "private"
        return f"astrbot-{group_id}-{event.get_sender_id()}"

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        return str(event.get_sender_id() or "").strip() in self._admin_ids()

    def _admin_ids(self) -> set[str]:
        configured = self._get_path(("permissions", "admin_qq_ids"), [])
        if isinstance(configured, list):
            ids = {str(item).strip() for item in configured if str(item).strip()}
            if ids:
                return ids
        raw = os.environ.get("ADMIN_QQ_IDS") or os.environ.get("NIKKE_GUILD_ADMIN_QQ_IDS") or ""
        return self._split_ids(raw)

    def _may_have_async_outputs(self, text: str, reply: Any) -> bool:
        normalized = text.lstrip("/／").strip()
        if normalized.startswith(("会战进度查询", "会战进度", "联盟突袭进度查询")):
            return True
        return "正在" in str(reply or "") and "完成后" in str(reply or "")

    def _get_path(self, path: tuple[str, ...], default: Any) -> Any:
        current: Any = self.config
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def _get_string(self, path: tuple[str, ...], default: str) -> str:
        value = self._get_path(path, default)
        return str(value or default)

    def _get_int(self, path: tuple[str, ...], default: int) -> int:
        value = self._get_path(path, default)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return default

    def _split_ids(self, raw: str) -> set[str]:
        return {item.strip() for item in raw.split(",") if item.strip()}
