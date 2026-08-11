from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .core import GuildWarBot
from .skills import default_registry
from .skills.base import IncomingMessage, SkillContext


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_API_URL = "http://127.0.0.1:3000"
SKILL_REGISTRY = default_registry()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m guild_war_bot.onebot_http",
        description="NapCat / OneBot HTTP POST 适配入口",
    )
    parser.add_argument("--host", default=os.environ.get("ONEBOT_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ONEBOT_PORT", DEFAULT_PORT)),
    )
    args = parser.parse_args(argv)

    bot = GuildWarBot()
    handler = build_handler(bot)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"OneBot HTTP 接收端已启动：http://{args.host}:{args.port}/onebot")
    print(f"NapCat API 地址：{os.environ.get('ONEBOT_API_URL', DEFAULT_API_URL)}")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        bot.close()
    return 0


def build_handler(bot: GuildWarBot) -> type[BaseHTTPRequestHandler]:
    class OneBotHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path.split("?", 1)[0] != "/onebot":
                self.send_json({"status": "not_found"}, status=404)
                return

            raw_body = read_request_body(self)
            try:
                event = decode_event(raw_body, self.headers.get("Content-Type", ""))
            except ValueError as exc:
                preview = raw_body.decode("utf-8", errors="replace")[:500]
                print(f"[OneBot] 无法解析上报内容：{exc}")
                print(f"[OneBot] Content-Type: {self.headers.get('Content-Type', '')}")
                print(f"[OneBot] Transfer-Encoding: {self.headers.get('Transfer-Encoding', '')}")
                print(f"[OneBot] Content-Length: {self.headers.get('Content-Length', '')}")
                print(f"[OneBot] Body preview: {preview}")
                self.send_json({"status": "bad_request", "message": str(exc)}, status=200)
                return

            try:
                reply = handle_onebot_event(bot, event)
                if reply:
                    send_reply(event, reply)
            except Exception as exc:  # Keep the callback alive for future events.
                print(f"[OneBot] 处理事件失败：{exc}")

            # OneBot HTTP POST treats the response as a "quick operation".
            # An empty object is the most compatible "no operation" response.
            self.send_json({})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[OneBot] {self.address_string()} - {fmt % args}")

        def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return OneBotHandler


def read_request_body(handler: BaseHTTPRequestHandler) -> bytes:
    transfer_encoding = handler.headers.get("Transfer-Encoding", "").lower()
    if "chunked" in transfer_encoding:
        chunks: list[bytes] = []
        while True:
            size_line = handler.rfile.readline().strip()
            if not size_line:
                break
            size = int(size_line.split(b";", 1)[0], 16)
            if size == 0:
                handler.rfile.readline()
                break
            chunks.append(handler.rfile.read(size))
            handler.rfile.readline()
        return b"".join(chunks)

    length = int(handler.headers.get("Content-Length", "0"))
    return handler.rfile.read(length)


def decode_event(raw_body: bytes, content_type: str) -> dict[str, Any]:
    text = raw_body.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("empty body")

    if "application/x-www-form-urlencoded" in content_type:
        form = parse_qs(text)
        for key in ("payload", "data", "event"):
            if key in form and form[key]:
                return json.loads(form[key][0])
        return {key: values[-1] for key, values in form.items()}

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"json decode error: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("event is not an object")
    return data


def handle_onebot_event(bot: GuildWarBot, event: dict[str, Any]) -> str | None:
    if event.get("post_type") != "message":
        return None

    message = command_text_from_event(event)
    if not message:
        if event.get("message_type") == "group":
            print("[OneBot] 群消息未识别为指令，已忽略。")
        return None

    sender_name = resolve_sender_name(event)
    user_id = str(event.get("user_id", ""))
    is_admin = user_id in admin_ids()
    print(f"[OneBot] 收到指令：sender={sender_name} qq={user_id} text={message}")
    incoming = IncomingMessage(
        raw_text=message,
        command=normalize_adapter_command(message),
        sender_name=sender_name,
        sender_qq=user_id,
        is_admin=is_admin,
        event=dict(event),
    )
    dispatch = SKILL_REGISTRY.dispatch(
        incoming,
        SkillContext(bot=bot, reply=OneBotReplyPort(event)),
    )
    if dispatch.handled:
        return dispatch.reply
    return bot.handle_message(
        sender_name,
        message,
        is_admin=is_admin,
        sender_qq=user_id,
    )


def normalize_adapter_command(message: str) -> str:
    return message.strip().lstrip("/／").strip()


def command_text_from_event(event: dict[str, Any]) -> str:
    message_type = event.get("message_type")
    message = event.get("message", "")
    if message_type != "group":
        return extract_plain_text(message)

    text = extract_plain_text(message)
    text = strip_cq_at(text).strip()
    mentioned = group_message_mentions_bot(event)
    if not mentioned and "/" in text:
        text = text[text.find("/") :]
    if not mentioned and "／" in text:
        text = text[text.find("／") :]
    if not text.startswith(("/", "／")):
        return ""
    return text


def group_message_mentions_bot(event: dict[str, Any]) -> bool:
    self_id = str(event.get("self_id", "")).strip()
    message = event.get("message", "")

    if isinstance(message, list):
        for item in message:
            if not isinstance(item, dict) or item.get("type") != "at":
                continue
            data = item.get("data") or {}
            target = str(data.get("qq", "")).strip()
            if target and target == self_id:
                return True
        return False

    if isinstance(message, str):
        return bool(self_id and f"[CQ:at,qq={self_id}]" in message)

    return False


def extract_plain_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts: list[str] = []
        for item in message:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                data = item.get("data") or {}
                parts.append(str(data.get("text", "")))
        return "".join(parts).strip()
    return ""


def strip_cq_at(text: str) -> str:
    return re.sub(r"\[CQ:at,qq=\d+\]", "", text)


def resolve_sender_name(event: dict[str, Any]) -> str:
    sender = event.get("sender") or {}
    for key in ("card", "nickname"):
        value = str(sender.get(key, "")).strip()
        if value:
            return value
    return str(event.get("user_id", "")).strip()


def admin_ids() -> set[str]:
    raw = os.environ.get("ADMIN_QQ_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


class OneBotReplyPort:
    def __init__(self, event: dict[str, Any]) -> None:
        self.event = event

    def send_text(self, message: str) -> None:
        send_reply(self.event, message)

    def send_image(self, image_path: Path, caption: str = "") -> None:
        send_image_reply(self.event, image_path, caption)


def send_reply(event: dict[str, Any], message: str) -> None:
    api_url = os.environ.get("ONEBOT_API_URL", DEFAULT_API_URL).rstrip("/")
    message_type = event.get("message_type")
    if message_type == "group":
        endpoint = "/send_group_msg"
        payload = {
            "group_id": event.get("group_id"),
            "message": message,
        }
    else:
        endpoint = "/send_private_msg"
        payload = {
            "user_id": event.get("user_id"),
            "message": message,
        }

    post_json(f"{api_url}{endpoint}", payload)


def send_image_reply(
    event: dict[str, Any],
    image_path: Path,
    caption: str = "",
) -> None:
    api_url = os.environ.get("ONEBOT_API_URL", DEFAULT_API_URL).rstrip("/")
    message_type = event.get("message_type")
    if message_type == "group":
        endpoint = "/send_group_msg"
        target = {"group_id": event.get("group_id")}
    else:
        endpoint = "/send_private_msg"
        target = {"user_id": event.get("user_id")}

    file_uri = image_path.resolve().as_uri()
    segments: list[dict[str, Any]] = []
    if caption:
        segments.append({"type": "text", "data": {"text": caption + "\n"}})
    segments.append({"type": "image", "data": {"file": file_uri}})
    post_json(f"{api_url}{endpoint}", {**target, "message": segments})


def post_json(url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("ONEBOT_ACCESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        print(f"[OneBot] 发送回复失败：{exc}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
