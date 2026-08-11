from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .core import GuildWarBot
from .onebot_http import normalize_adapter_command
from .skills import default_registry
from .skills.base import IncomingMessage, SkillContext
from .skills.registry import SkillRegistry


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8793
MAX_BODY_BYTES = 128 * 1024


@dataclass(frozen=True)
class OutboxMessage:
    id: int
    type: str
    text: str = ""
    path: str = ""
    caption: str = ""

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "type": self.type}
        if self.text:
            data["text"] = self.text
        if self.path:
            data["path"] = self.path
        if self.caption:
            data["caption"] = self.caption
        return data


class BridgeOutbox:
    def __init__(self, max_messages_per_session: int = 200) -> None:
        self.max_messages_per_session = max_messages_per_session
        self.lock = threading.Lock()
        self.next_id = 1
        self.messages: dict[str, list[OutboxMessage]] = {}

    def append_text(self, session_id: str, text: str) -> None:
        self._append(session_id, OutboxMessage(id=0, type="text", text=text))

    def append_image(self, session_id: str, image_path: Path, caption: str = "") -> None:
        self._append(
            session_id,
            OutboxMessage(
                id=0,
                type="image",
                path=str(image_path.resolve()),
                caption=caption,
            ),
        )

    def read_after(self, session_id: str, after: int = 0) -> list[OutboxMessage]:
        with self.lock:
            return [
                message
                for message in self.messages.get(session_id, [])
                if message.id > after
            ]

    def _append(self, session_id: str, message: OutboxMessage) -> None:
        with self.lock:
            message = OutboxMessage(
                id=self.next_id,
                type=message.type,
                text=message.text,
                path=message.path,
                caption=message.caption,
            )
            self.next_id += 1
            bucket = self.messages.setdefault(session_id, [])
            bucket.append(message)
            if len(bucket) > self.max_messages_per_session:
                del bucket[: len(bucket) - self.max_messages_per_session]


class BridgeReplyPort:
    def __init__(self, outbox: BridgeOutbox, session_id: str) -> None:
        self.outbox = outbox
        self.session_id = session_id

    def send_text(self, message: str) -> None:
        self.outbox.append_text(self.session_id, message)

    def send_image(self, image_path: Path, caption: str = "") -> None:
        self.outbox.append_image(self.session_id, image_path, caption)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m guild_war_bot.service_http",
        description="Local HTTP bridge for AstrBot or other bot frontends.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    bot = GuildWarBot()
    outbox = BridgeOutbox()
    handler = build_handler(bot, default_registry(), outbox)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"AstrBot bridge service started: http://{args.host}:{args.port}")
    print("POST /command, GET /outbox, GET /health")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        bot.close()
    return 0


def build_handler(
    bot: GuildWarBot,
    registry: SkillRegistry | None = None,
    outbox: BridgeOutbox | None = None,
) -> type[BaseHTTPRequestHandler]:
    registry = registry or default_registry()
    outbox = outbox or BridgeOutbox()

    class BridgeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self.send_json({"ok": True, "service": "guild_war_bot_bridge"})
                return
            if parsed.path == "/outbox":
                query = parse_qs(parsed.query)
                session_id = (query.get("session_id") or [""])[0].strip()
                after = parse_int((query.get("after") or ["0"])[0], default=0)
                if not session_id:
                    self.send_json(
                        {"ok": False, "error": "session_id is required"},
                        status=400,
                    )
                    return
                messages = outbox.read_after(session_id, after)
                next_after = messages[-1].id if messages else after
                self.send_json(
                    {
                        "ok": True,
                        "session_id": session_id,
                        "messages": [message.to_json() for message in messages],
                        "next_after": next_after,
                    }
                )
                return
            self.send_json({"ok": False, "error": "not_found"}, status=404)

        def do_POST(self) -> None:
            if self.path.split("?", 1)[0] != "/command":
                self.send_json({"ok": False, "error": "not_found"}, status=404)
                return
            try:
                payload = self.read_json_body()
                result = handle_bridge_command(bot, payload, registry, outbox)
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            except Exception as exc:  # Keep bridge alive for future requests.
                print(f"[AstrBotBridge] command failed: {type(exc).__name__}: {exc}")
                self.send_json({"ok": False, "error": str(exc)}, status=500)
                return
            self.send_json(result)

        def read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("empty body")
            if length > MAX_BODY_BYTES:
                raise ValueError("body too large")
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid json: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("body must be a json object")
            return data

        def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[AstrBotBridge] {self.address_string()} - {fmt % args}")

    return BridgeHandler


def handle_bridge_command(
    bot: GuildWarBot,
    payload: dict[str, Any],
    registry: SkillRegistry | None = None,
    outbox: BridgeOutbox | None = None,
) -> dict[str, Any]:
    text = str(payload.get("text", "")).strip()
    if not text:
        raise ValueError("text is required")

    session_id = str(payload.get("session_id") or uuid.uuid4()).strip()
    sender_name = str(payload.get("sender_name") or payload.get("sender") or "").strip()
    sender_qq = str(payload.get("sender_qq") or payload.get("qq") or "").strip()
    if not sender_name:
        sender_name = sender_qq or "AstrBot"
    is_admin = bool(payload.get("is_admin", False))

    registry = registry or default_registry()
    outbox = outbox or BridgeOutbox()
    incoming = IncomingMessage(
        raw_text=text,
        command=normalize_adapter_command(text),
        sender_name=sender_name,
        sender_qq=sender_qq,
        is_admin=is_admin,
        event={
            "source": "astrbot_bridge",
            "session_id": session_id,
            "raw": dict(payload),
        },
    )
    dispatch = registry.dispatch(
        incoming,
        SkillContext(bot=bot, reply=BridgeReplyPort(outbox, session_id)),
    )
    if dispatch.handled:
        reply = dispatch.reply
        handled = True
    else:
        reply = bot.handle_message(
            sender_name,
            text,
            is_admin=is_admin,
            sender_qq=sender_qq or None,
        )
        handled = reply is not None

    return {
        "ok": True,
        "session_id": session_id,
        "handled": handled,
        "reply": reply,
    }


def parse_int(raw: str, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
