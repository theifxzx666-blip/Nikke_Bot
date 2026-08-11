from __future__ import annotations

import threading

from game_progress_query import capture_progress

from .base import IncomingMessage, SkillContext


class GameProgressSkill:
    name = "game_progress"
    commands = {"会战进度查询", "会战进度", "联盟突袭进度查询"}

    def __init__(self) -> None:
        self.lock = threading.Lock()

    def matches(self, message: IncomingMessage) -> bool:
        return message.command in self.commands

    def handle(self, message: IncomingMessage, context: SkillContext) -> str | None:
        if not self.lock.acquire(blocking=False):
            return "已有会战进度查询正在执行，请稍后再试。"
        print("[OneBot] 会战进度查询任务已入队。")
        threading.Thread(
            target=self._run,
            args=(context, dict(message.event)),
            name="game-progress-query",
            daemon=True,
        ).start()
        return "收到，正在进入游戏查询会战进度，完成后会发送截图。"

    def _run(self, context: SkillContext, event: dict) -> None:
        try:
            print("[OneBot] 开始执行会战进度查询。")
            result = capture_progress()
            image_paths = result.image_paths or [result.image_path]
            if len(image_paths) == 1:
                caption = f"会战进度查询完成\nBoss 血量合成预览\n截图时间：{result.captured_at}"
                context.reply.send_image(image_paths[0], caption)
            else:
                context.reply.send_text(
                    f"会战进度查询完成，共 {len(image_paths)} 张 Boss 血量截图。\n"
                    f"截图时间：{result.captured_at}"
                )
                labels = ["I", "II", "III", "IV", "V"]
                for index, image_path in enumerate(image_paths):
                    label = labels[index] if index < len(labels) else str(index + 1)
                    context.reply.send_image(image_path, f"Boss {label}")
            print(f"[OneBot] 会战进度截图已发送：{image_paths}")
        except Exception as exc:
            print(f"[OneBot] 会战进度查询失败：{type(exc).__name__}: {exc}")
            context.reply.send_text(f"会战进度查询失败：{exc}")
        finally:
            self.lock.release()
