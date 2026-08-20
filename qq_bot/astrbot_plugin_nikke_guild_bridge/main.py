from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

import aiohttp
from astrbot.api import AstrBotConfig
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import File, Image
from astrbot.api.star import Context, Star, StarTools

# AstrBot 运行目录通常是 supports/AstrBot；将本项目根目录显式加入导入路径，
# 使已安装插件和源码插件都能共享 guild_war_bot/wiki_query。
def _ensure_project_root() -> Path:
    configured = os.environ.get("NIKKE_BOT_ROOT")
    candidates = [Path(configured)] if configured else []
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / "guild_war_bot").is_dir() and (candidate / "data").is_dir():
            root = str(candidate)
            if root not in sys.path:
                sys.path.insert(0, root)
            return candidate
    raise RuntimeError("无法定位 Nikke_Bot 项目根目录，请设置 NIKKE_BOT_ROOT")


PROJECT_ROOT = _ensure_project_root()

from guild_war_bot.wiki_query.catalog import AffixCatalog, load_json
from guild_war_bot.wiki_query.equipment_session import SessionManager, Step, parse_affix_command
from guild_war_bot.wiki_query.equipment_store import EquipmentStore
from guild_war_bot.wiki_query.ocr import AffixOCR
from guild_war_bot.wiki_query import default_index
from guild_war_bot.wiki_query.summarize import character_portrait_path


DEFAULT_BRIDGE_URL = "http://127.0.0.1:8793"
POLL_INTERVAL_SECONDS = 2
POLL_ATTEMPTS = 60
REQUEST_TIMEOUT_SECONDS = 10


def _normalize_skill_command(text: str) -> str:
    return str(text or "").strip().lstrip("#＃/／").strip()


def _load_disabled_skill_prefixes() -> set[str]:
    path = PROJECT_ROOT / "manager" / "manager_config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        _normalize_skill_command(item.get("command", ""))
        for item in config.get("skills", [])
        if isinstance(item, dict) and not item.get("enabled", True) and item.get("command")
    }

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
    "培养",
    "培养建议",
    "怎么培养",
    "养成",
    "养成建议",
}

class OCRGate:
    def __init__(self, max_per_second: int = 2) -> None:
        self.max_per_second = max_per_second
        self.calls: deque[float] = deque()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self.lock:
                now = monotonic()
                while self.calls and now - self.calls[0] >= 1:
                    self.calls.popleft()
                if len(self.calls) < self.max_per_second:
                    self.calls.append(now)
                    return
                delay = 1 - (now - self.calls[0])
            await asyncio.sleep(max(0.05, delay))


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
        plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_nikke_guild_bridge")
        self.affix_data_dir = Path(plugin_data_dir)
        self.affix_catalog = AffixCatalog(PROJECT_ROOT / "data" / "equipment_affix_catalog.json")
        self.character_equip_catalog = load_json(PROJECT_ROOT / "data" / "character_equip_catalog.json")
        self.affix_ocr = AffixOCR(self.affix_catalog.rules)
        self.affix_store = EquipmentStore(self.affix_data_dir / "equipment_affix.db")
        self.affix_sessions = SessionManager(self.affix_store)
        self.affix_index = default_index()
        self.affix_tasks: set[asyncio.Task[Any]] = set()
        self.affix_cleanup_task: asyncio.Task[Any] | None = None
        self.affix_user_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.affix_ocr_gate = OCRGate(max_per_second=2)
        self.disabled_skill_prefixes = _load_disabled_skill_prefixes()

    @filter.event_message_type(filter.EventMessageType.ALL, priority=900)
    async def affix_message(self, event: AstrMessageEvent):
        """独立处理词条命令和导入会话中的图片，不进入 8793 会战桥接。"""
        self._ensure_affix_cleanup_task()
        command = self._parse_affix_command(event.message_str or "")
        image = next(
            (item for item in getattr(event.message_obj, "message", []) if isinstance(item, Image)),
            None,
        )
        if command is None and image is None:
            return
        if command is not None:
            if not self._skill_enabled(event.message_str):
                yield event.plain_result("该技能已在机器人管理客户端中停用。")
                event.stop_event()
                return
            reply = await self._handle_affix_command(event, command[0], command[1])
            if reply:
                yield event.plain_result(reply)
            event.stop_event()
            return
        session = await self.affix_sessions.get(event.get_sender_id())
        if not session or session.step != Step.WAITING_SCREENSHOT_N:
            return
        yield event.plain_result("已收到截图，正在识别，请稍候。")
        self._start_affix_task(self._process_affix_image(
            event.unified_msg_origin, str(event.get_sender_id()), image,
        ))
        event.stop_event()

    def _ensure_affix_cleanup_task(self) -> None:
        if self.affix_cleanup_task is None or self.affix_cleanup_task.done():
            self.affix_cleanup_task = asyncio.create_task(self.affix_sessions.cleanup_loop())

    def _start_affix_task(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.affix_tasks.add(task)
        task.add_done_callback(self.affix_tasks.discard)

    def _skill_enabled(self, text: str) -> bool:
        command = _normalize_skill_command(text)
        return not any(command == prefix or command.startswith(prefix + " ") for prefix in self.disabled_skill_prefixes)

    @staticmethod
    def _parse_affix_command(text: str) -> tuple[str, str] | None:
        return parse_affix_command(text)

    async def _handle_affix_command(self, event: AstrMessageEvent, command: str, argument: str) -> str | None:
        user_id = event.get_sender_id()
        if command == "词条导入":
            character_query, requested_slots = self._parse_import_argument(argument)
            character = self.affix_index.lookup(character_query)
            if not character:
                return f"未找到角色「{character_query}」，请使用 Wiki 中的正式名称或别名。"
            character_id = str(character.get("url") or character.get("name") or character_query)
            slots = list(range(1, requested_slots + 1)) if requested_slots else self._character_slots(character_id)
            self.affix_store.ensure_user(user_id, event.get_sender_name())
            await self.affix_sessions.start(user_id, {"id": character_id, "name": character.get("cnName") or character_query}, len(slots))
            return f"已开始导入「{character.get('cnName') or character_query}」，请依次发送 {len(slots)} 张装备截图。"
        if command == "词条取消":
            await self.affix_sessions.cancel(user_id)
            return "已取消当前词条导入，不会修改已确认数据。"
        if command == "词条重试":
            session = await self.affix_sessions.get(user_id)
            if not session:
                return "当前没有可重试的词条导入任务。"
            return "请重新发送上一张装备截图。"
        if command == "词条确认":
            return await self._confirm_affixes(user_id)
        if command == "词条修正":
            return await self._correct_affix(user_id, argument)
        if command == "词条":
            return self._query_affix_text(user_id, argument)
        if command == "词条统计":
            prepared = self._filter_affixes(user_id, argument)
            if prepared is None:
                return "没有找到已确认的词条数据。"
            rows, character = prepared
            self._start_affix_task(self._render_affix_stats(
                event.unified_msg_origin, str(user_id), argument, rows, character,
            ))
            return "已收到词条统计请求，正在后台生成图片。"
        if command == "词条导出":
            if not self.affix_store.list_affixes(user_id):
                return "当前没有可导出的已确认词条。"
            self._start_affix_task(self._export_affixes(event.unified_msg_origin, str(user_id)))
            return "已收到词条导出请求，正在后台生成 Excel。"
        return "用法：#词条导入 角色名、#词条 角色名、#词条统计 角色名/属性、#词条导出"

    @staticmethod
    def _parse_import_argument(argument: str) -> tuple[str, int | None]:
        parts = argument.rsplit(maxsplit=1)
        if len(parts) == 2 and parts[1] in {"4", "5"}:
            return parts[0], int(parts[1])
        return argument, None

    def _character_slots(self, character_id: str) -> list[int]:
        rule = self._character_rule(character_id)
        slots = rule.get("slots") or [1, 2, 3, 4]
        return [int(slot) for slot in slots]

    def _character_rule(self, character_id: str) -> dict[str, Any]:
        rule = dict(self.character_equip_catalog.get("_default") or {})
        for name, item in self.character_equip_catalog.items():
            if name != "_default" and item.get("character_id") == character_id:
                rule.update(item)
                break
        return rule

    async def _process_affix_image(self, origin: str, user_id: str, image: Image) -> None:
        try:
            async with self.affix_user_locks[user_id]:
                temporary_path = Path(await image.convert_to_file_path())
                path = await asyncio.to_thread(self._archive_affix_image, temporary_path)
                current = await self.affix_sessions.get(user_id)
                if not current or current.step != Step.WAITING_SCREENSHOT_N:
                    return
                completed = {int(row.get("slot") or 0) for row in current.payload.get("rows", [])}
                expected = int(current.payload.get("expected") or 4)
                slot = next((number for number in range(1, expected + 1) if number not in completed), expected)
                cached = self.affix_store.cached_ocr(user_id, path)
                if cached is None:
                    await self.affix_ocr_gate.acquire()
                    result = await asyncio.to_thread(self.affix_ocr.process, path, slot)
                    ocr_id = self.affix_store.save_ocr(user_id, path, result)
                else:
                    result = cached
                    ocr_id = int(cached["ocr_id"])
                rows = [dict(row, slot=slot, source_ocr_id=ocr_id) for row in result.get("rows", [])]
                if not rows:
                    await StarTools.send_message(
                        origin,
                        MessageChain().message("未识别到有效词条，本张未计入进度。请重新截图，或发送 #词条修正 槽位 属性 数值 阶数。"),
                    )
                    return
                updated = await self.affix_sessions.add_result(user_id, str(path), rows)
                if updated is None:
                    return
                received = len({int(row.get("slot") or 0) for row in updated.payload.get("rows", [])})
                summary = self._format_ocr_summary(rows)
                review = result.get("status") == "needs_review"
                if updated.step == Step.WAITING_CONFIRM:
                    next_text = "请核对后发送 #词条确认，或用 #词条修正 调整。"
                else:
                    next_text = "请继续发送下一张装备截图。"
                prefix = "识别结果需人工确认" if review else "识别完成"
                message = f"{prefix}（{received}/{expected}）：\n{summary}\n{next_text}"
                await StarTools.send_message(origin, MessageChain().message(message))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("NIKKE affix OCR failed: %s", exc)
            await StarTools.send_message(
                origin,
                MessageChain().message("词条识别失败，请发送 #词条重试，或使用 #词条修正 手动录入。"),
            )

    def _archive_affix_image(self, source: Path) -> Path:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        suffix = source.suffix.lower() if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
        target = self.affix_data_dir / "imports" / datetime.now().strftime("%Y%m%d") / f"{digest}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
        return target

    @staticmethod
    def _format_ocr_summary(rows: list[dict[str, Any]]) -> str:
        lines = []
        for row in rows:
            tier = f"{row.get('tier')}阶" if int(row.get("tier") or 0) else "阶数待确认"
            confidence = float(row.get("confidence") or 0)
            confidence_text = f"，置信度 {confidence:.0%}" if confidence < 0.80 else ""
            lines.append(f"装备{row.get('slot')} {row.get('affix_type')} {row.get('value_text')}，{tier}{confidence_text}")
        return "\n".join(lines)

    async def _confirm_affixes(self, user_id: str) -> str:
        session = await self.affix_sessions.get(user_id)
        if not session or session.step != Step.WAITING_CONFIRM:
            return "当前没有待确认的词条结果，或截图数量尚未达到要求。"
        character = session.payload.get("character") or {}
        rows = session.payload.get("rows") or []
        count = self.affix_store.commit_affixes(
            user_id, str(character.get("id")), str(character.get("name")), rows,
        )
        await self.affix_sessions.finish(user_id)
        return f"已确认保存「{character.get('name', '角色')}」词条，共 {count} 条。"

    async def _correct_affix(self, user_id: str, argument: str) -> str:
        session = await self.affix_sessions.get(user_id)
        if not session:
            return "当前没有待修正的词条导入任务。"
        parts = argument.split()
        if len(parts) < 4:
            return "用法：#词条修正 槽位 词条类型 数值 阶数，例如 #词条修正 2 攻击力 8.2% 2"
        try:
            slot = int(parts[0])
            value_text = parts[2].replace("％", "%")
            value = float(value_text.rstrip("%"))
            tier = int(parts[3])
            affix_type = self.affix_catalog.normalize_type(parts[1])
            expected = int(session.payload.get("expected") or 4)
            if slot not in range(1, expected + 1) or tier not in range(0, 16) or not affix_type:
                raise ValueError
        except ValueError:
            return "槽位需在当前导入范围内、属性需使用支持的名称、数值需为数字、阶数需为 0-15。"
        row = {"slot": slot, "affix_type": affix_type, "affix_value": value, "value_text": value_text, "tier": tier, "confidence": 1.0}
        updated = await self.affix_sessions.correct_row(user_id, row)
        if updated is None:
            return "当前会话不可修正，请重新发送 #词条导入 角色名。"
        tier_text = f"{tier}阶" if tier else "阶数待确认"
        suffix = " 已达到要求，可发送 #词条确认。" if updated.step == Step.WAITING_CONFIRM else ""
        return f"已修正装备 {slot} 的「{affix_type}」为 {value_text}（{tier_text}）。{suffix}"

    def _filter_affixes(self, user_id: str, argument: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None] | None:
        rows = self.affix_store.list_affixes(user_id)
        character = None
        if argument:
            character = self.affix_index.lookup(argument)
            if character:
                character_id = str(character.get("url") or character.get("name"))
                rows = [row for row in rows if row["character_id"] == character_id]
            else:
                affix_type = self.affix_catalog.normalize_type(argument) or argument
                rows = [row for row in rows if row["affix_type"] == affix_type]
        if not rows:
            return None
        return rows, character

    def _query_affix_text(self, user_id: str, argument: str) -> str:
        prepared = self._filter_affixes(user_id, argument)
        if prepared is None:
            return "没有找到已确认的词条数据。"
        rows, _ = prepared
        return "\n".join(
            f"{row['character_name']} 装备{row['slot']}：{row['affix_type']} {row['value_text']}（{self._tier_text(row)}）"
            for row in rows
        )

    @staticmethod
    def _tier_text(row: dict[str, Any]) -> str:
        tier = int(row.get("tier") or 0)
        return f"{tier}阶" if tier else "阶数待确认"

    async def _render_affix_stats(
        self,
        origin: str,
        user_id: str,
        argument: str,
        rows: list[dict[str, Any]],
        character: dict[str, Any] | None,
    ) -> None:
        try:
            if character:
                output = self.affix_data_dir / "renders" / f"card_{user_id}_{character.get('url') or character.get('name')}.png"
                portrait = character_portrait_path(character)
                card_character = dict(character)
                card_character.update(self._character_rule(str(character.get("url") or character.get("name") or "")))
                await asyncio.to_thread(
                    self.affix_catalog.render_card,
                    card_character,
                    rows,
                    output,
                    Path(portrait) if portrait else None,
                )
                message = f"已生成「{character.get('cnName') or argument}」词条卡片，共 {len(rows)} 条。"
            else:
                output = self.affix_data_dir / "renders" / f"compare_{user_id}.png"
                await asyncio.to_thread(self.affix_catalog.render_compare, rows, output)
                message = f"已生成词条对比表，共匹配 {len(rows)} 条记录。"
            await StarTools.send_message(origin, MessageChain().message(message))
            await StarTools.send_message(origin, MessageChain().file_image(str(output)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("NIKKE affix render failed: %s", exc)
            await StarTools.send_message(origin, MessageChain().message("词条统计图片生成失败，请稍后重试。"))

    async def _export_affixes(self, origin: str, user_id: str) -> None:
        try:
            rows = self.affix_store.list_affixes(user_id)
            if not rows:
                await StarTools.send_message(origin, MessageChain().message("当前没有可导出的已确认词条。"))
                return
            filename = f"equipment_affixes_{user_id}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
            path = self.affix_data_dir / "exports" / filename
            await asyncio.to_thread(self.affix_catalog.export_xlsx, rows, path)
            await StarTools.send_message(origin, MessageChain(chain=[File(name=filename, file=str(path))]))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("NIKKE affix export failed: %s", exc)
            await StarTools.send_message(origin, MessageChain().message("词条 Excel 生成失败，请稍后重试。"))

    async def terminate(self) -> None:
        tasks = list(self.affix_tasks)
        if self.affix_cleanup_task and not self.affix_cleanup_task.done():
            self.affix_cleanup_task.cancel()
            tasks.append(self.affix_cleanup_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.affix_tasks.clear()
        self.affix_user_locks.clear()

    @filter.command("查刀", alias=COMMAND_ALIASES)
    async def guild_command(self, event: AstrMessageEvent):
        """转发 NIKKE 公会战指令到本地桥接服务。"""
        text = event.message_str.strip()
        if not text:
            return
        if not self._skill_enabled(text):
            yield event.plain_result("该技能已在机器人管理客户端中停用。")
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
        # 会发图的命令：会战进度截图、角色卡立绘、养成建议截图、wiki 查询等
        if normalized.startswith(
            (
                "会战进度查询",
                "会战进度",
                "联盟突袭进度查询",
                "角色",
                "查角色",
                "角色卡",
                "是谁",
                "wiki",
                "养成",
                "养成建议",
                "培养",
                "培养建议",
                "加点",
                "怎么培养",
                "查 ",
            )
        ):
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
