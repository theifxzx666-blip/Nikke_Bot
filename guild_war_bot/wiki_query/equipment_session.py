from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


AFFIX_COMMAND_PATTERN = re.compile(
    r"^[#＃/／](词条导入|词条统计|词条导出|词条确认|词条修正|词条重试|词条取消|词条)"
    r"(?:\s+(.*))?$"
)


def parse_affix_command(text: str) -> tuple[str, str] | None:
    match = AFFIX_COMMAND_PATTERN.match(text.strip())
    if not match:
        return None
    return match.group(1), (match.group(2) or "").strip()


class Step(StrEnum):
    IDLE = "IDLE"
    WAITING_SCREENSHOT_N = "WAITING_SCREENSHOT_N"
    WAITING_CONFIRM = "WAITING_CONFIRM"
    COMPLETE = "COMPLETE"


@dataclass
class Session:
    user_id: str
    step: Step = Step.IDLE
    payload: dict[str, Any] = field(default_factory=dict)
    touched_at: float = field(default_factory=time.time)


class SessionManager:
    def __init__(self, store, timeout_seconds: int = 1800) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.items: dict[str, Session] = {}
        self.lock = asyncio.Lock()

    async def start(self, user_id: str, character: dict[str, Any], expected: int) -> Session:
        session = Session(
            str(user_id), Step.WAITING_SCREENSHOT_N,
            {"character": character, "expected": expected, "images": [], "rows": []},
        )
        async with self.lock:
            self.items[session.user_id] = session
            self._save(session)
        return session

    async def get(self, user_id: str) -> Session | None:
        async with self.lock:
            session = self.items.get(str(user_id)) or self._load(user_id)
            if session and self._expired(session):
                self._delete(user_id)
                return None
            if session:
                self.items[session.user_id] = session
            return session

    async def add_result(self, user_id: str, image_path: str, rows: list[dict[str, Any]]) -> Session | None:
        if not rows:
            return await self.get(user_id)
        async with self.lock:
            session = self.items.get(str(user_id)) or self._load(user_id)
            if not session or self._expired(session) or session.step != Step.WAITING_SCREENSHOT_N:
                self._delete(user_id)
                return None
            session.payload.setdefault("images", []).append(image_path)
            session.payload.setdefault("rows", []).extend(rows)
            expected = int(session.payload.get("expected") or 4)
            completed_slots = {int(item.get("slot") or 0) for item in session.payload["rows"]}
            if len(completed_slots) >= expected:
                session.step = Step.WAITING_CONFIRM
            session.touched_at = time.time()
            self.items[session.user_id] = session
            self._save(session)
            return session

    async def correct_row(self, user_id: str, row: dict[str, Any]) -> Session | None:
        async with self.lock:
            session = self.items.get(str(user_id)) or self._load(user_id)
            if not session or self._expired(session) or session.step not in {
                Step.WAITING_SCREENSHOT_N, Step.WAITING_CONFIRM,
            }:
                self._delete(user_id)
                return None
            slot = int(row["slot"])
            affix_type = str(row["affix_type"])
            rows = [
                item for item in session.payload.get("rows", [])
                if not (int(item.get("slot") or 0) == slot and item.get("affix_type") == affix_type)
            ]
            rows.append(row)
            session.payload["rows"] = rows
            completed_slots = {int(item.get("slot") or 0) for item in rows}
            if len(completed_slots) >= int(session.payload.get("expected") or 4):
                session.step = Step.WAITING_CONFIRM
            session.touched_at = time.time()
            self.items[session.user_id] = session
            self._save(session)
            return session

    async def finish(self, user_id: str) -> None:
        async with self.lock:
            session = self.items.get(str(user_id))
            if session:
                session.step = Step.COMPLETE
                self._save(session)
            self.items.pop(str(user_id), None)
            self._delete(user_id)

    async def cancel(self, user_id: str) -> None:
        async with self.lock:
            self.items.pop(str(user_id), None)
            self._delete(user_id)

    async def cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            async with self.lock:
                for user_id, session in list(self.items.items()):
                    if self._expired(session):
                        self.items.pop(user_id, None)
                        self._delete(user_id)

    def _expired(self, session: Session) -> bool:
        return time.time() - session.touched_at > self.timeout_seconds

    def _save(self, session: Session) -> None:
        self.store.save_session(session.user_id, session.step.value, {
            **session.payload, "touched_at": session.touched_at,
        })

    def _load(self, user_id: str) -> Session | None:
        row = self.store.load_session(user_id)
        if not row:
            return None
        payload = json.loads(row["payload_json"] or "{}")
        touched_at = float(payload.pop("touched_at", time.time()))
        return Session(str(user_id), Step(row["step"]), payload, touched_at)

    def _delete(self, user_id: str) -> None:
        self.store.delete_session(str(user_id))
