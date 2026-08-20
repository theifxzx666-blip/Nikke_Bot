# -*- coding: utf-8 -*-
"""NIKKE QQ 机器人通信链路保险系统（Watchdog）。

职责：掉线检测 -> 自动重连 -> 重连失败钉钉告警。
- 纯标准库实现，零第三方依赖，可 `pythonw.exe watchdog.py` 无窗口后台运行。
- 配置见同目录 watchdog_config.json。

用法：
    python watchdog.py             # 守护模式（默认）
    python watchdog.py --check     # 只跑一轮检查后退出（手动验证用）
    python watchdog.py --once      # 同 --check
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("watchdog_config.json")
LOG_PATH = Path(__file__).with_name("watchdog.log")

logger = logging.getLogger("nikke-watchdog")

# Windows 下给子进程开独立控制台窗口，方便观察服务日志
CREATE_NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0


# ---------------------------------------------------------------- 检测器

def check_process(process: str) -> bool:
    """进程存在性检查（tasklist）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process}"],
            capture_output=True, text=True, encoding="mbcs", errors="replace", timeout=15,
        ).stdout or ""
        return process.lower() in out.lower()
    except (subprocess.SubprocessError, OSError):
        return False


def check_tcp(host: str, port: int) -> bool:
    """TCP 端口监听检查。"""
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def check_tcp_established(port: int) -> bool:
    """OneBot WS 链路检查：6199 端口是否存在 ESTABLISHED 连接。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True,
            encoding="mbcs", errors="replace", timeout=15,
        ).stdout or ""
        for line in out.splitlines():
            if f":{port}" in line and "ESTABLISHED" in line:
                return True
        return False
    except (subprocess.SubprocessError, OSError):
        return False


def check_http(url: str, expect_ok: bool = False) -> bool:
    """HTTP 健康检查；expect_ok=True 时要求返回 JSON 里 ok 为真。"""
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status != 200:
                return False
            if expect_ok:
                body = resp.read().decode("utf-8", "ignore").strip()
                try:
                    return bool(json.loads(body).get("ok"))
                except (json.JSONDecodeError, AttributeError):
                    return "ok" in body.lower() and "true" in body.lower()
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def check_target(target: dict) -> bool:
    """按类型分发检测。"""
    kind = target.get("type")
    if kind == "process":
        return check_process(target["process"])
    if kind == "tcp":
        return check_tcp(target.get("host", "127.0.0.1"), target["port"])
    if kind == "tcp_established":
        return check_tcp_established(target["port"])
    if kind == "http":
        return check_http(target["url"], bool(target.get("expect_ok")))
    return True


# ---------------------------------------------------------------- 钉钉告警

def dingtalk_sign(timestamp: str, secret: str) -> str:
    """钉钉机器人加签：HMAC-SHA256(key=secret, msg=timestamp+\\n+secret) -> base64。"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256,
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code))


def dingtalk_send(webhook: str, secret: str, title: str, text: str) -> bool:
    """发送钉钉 markdown 消息，加签模式（timestamp+sign 拼在 webhook URL 参数里）。"""
    timestamp = str(round(time.time() * 1000))
    sign = dingtalk_sign(timestamp, secret)
    sep = "&" if "?" in webhook else "?"
    url = f"{webhook}{sep}timestamp={timestamp}&sign={sign}"
    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", "ignore")
            result = json.loads(body)
            if result.get("errcode") == 0:
                return True
            logger.warning("钉钉返回错误: %s", body[:200])
            return False
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning("钉钉发送失败: %s", exc)
        return False


# ---------------------------------------------------------------- 主逻辑

class Watchdog:
    def __init__(self, config: dict) -> None:
        self.root = Path(__file__).resolve().parent  # 项目根（watchdog 所在目录）
        self.cfg = config
        self.targets: list[dict] = config.get("targets", [])
        self.services: dict[str, dict] = config.get("services", {})
        self.threshold = int(config.get("fail_threshold", 2))
        self.interval = float(config.get("check_interval", 10))
        self.retry = config.get("retry", {"max_attempts": 3, "backoff_seconds": [10, 30, 60]})
        self.max_attempts = int(self.retry.get("max_attempts", 3))
        self.backoff = [float(x) for x in self.retry.get("backoff_seconds", [10, 30, 60])]
        self.alert_cfg = config.get("alert", {})
        self.cooldown = float(self.alert_cfg.get("cooldown_minutes", 30)) * 60
        self.notify_recover = bool(self.alert_cfg.get("notify_on_recover", True))

        # 状态：target 连续失败计数 / service 重连状态机 / service 告警冷却
        self.fail_counts: dict[str, int] = {}
        self.restart_state: dict[str, dict] = {}   # service -> {attempt, next_ts}
        self.alert_ts: dict[str, float] = {}
        self.recovered_ts: dict[str, float] = {}

    # ---- 检测 ----
    def run_checks(self) -> dict[str, list[dict]]:
        """跑一轮所有检查，返回 {ok: [...], fail: [...]}。"""
        ok, fail = [], []
        for target in self.targets:
            name = target["name"]
            if check_target(target):
                ok.append(target)
                self.fail_counts[name] = 0
            else:
                fail.append(target)
                self.fail_counts[name] = self.fail_counts.get(name, 0) + 1
        return {"ok": ok, "fail": fail}

    # ---- 重连 ----
    def _service_cwd(self, spec: dict) -> str:
        """解析服务工作目录：相对路径以项目根为基准，保证便携可移动。"""
        cwd = spec.get("cwd") or "."
        path = Path(cwd)
        return str(self.root / path) if not path.is_absolute() else str(path)

    def restart_service(self, service: str, reason: str) -> None:
        """启动一个服务的重启动作（幂等：同一服务同一秒不重复）。"""
        spec = self.services.get(service)
        if not spec:
            return
        now = time.time()
        state = self.restart_state.get(service)
        if state and state.get("next_ts", 0) > now:
            return  # 仍在退避等待中

        attempt = (state.get("attempt", 0) + 1) if state else 1
        if attempt > self.max_attempts:
            self._alert_if_needed(service, reason, "重连尝试 %d 次全部失败" % self.max_attempts)
            self.restart_state[service] = {"attempt": 1, "next_ts": now + self.cooldown}
            return

        delay = self.backoff[min(attempt - 1, len(self.backoff) - 1)]
        logger.warning("[%s] 第 %d 次重启: %s", service, attempt, reason)
        try:
            subprocess.Popen(
                spec["cmd"],
                cwd=self._service_cwd(spec),
                creationflags=CREATE_NEW_CONSOLE,
                close_fds=True,
            )
        except OSError as exc:
            logger.error("[%s] 重启进程失败: %s", service, exc)

        self.restart_state[service] = {"attempt": attempt, "next_ts": now + delay}

    # ---- 告警 ----
    def _alert_if_needed(self, service: str, reason: str, detail: str) -> None:
        """带冷却的钉钉告警。"""
        now = time.time()
        if now - self.alert_ts.get(service, 0) < self.cooldown:
            return
        self.alert_ts[service] = now
        self.recovered_ts[service] = now
        webhook = self.alert_cfg.get("dingtalk_webhook")
        if not webhook:
            logger.error("[%s] 未配置钉钉 webhook，跳过告警", service)
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        text = (
            f"### 🔴 机器人守护告警\n\n"
            f"- **时间**: {stamp}\n"
            f"- **服务**: {service}（{reason}）\n"
            f"- **详情**: {detail}\n"
            f"- **建议**: 检查对应服务窗口/日志，必要时手动处理"
        )
        if dingtalk_send(webhook, self.alert_cfg.get("dingtalk_secret", ""), "机器人守护告警", text):
            logger.warning("[%s] 钉钉告警已发送", service)

    # ---- 恢复通知 ----
    def _notify_recover(self, service: str) -> None:
        if not self.notify_recover:
            return
        now = time.time()
        if now - self.recovered_ts.get(service, 0) >= self.cooldown:
            return  # 告警冷却已过，视为正常
        self.recovered_ts[service] = 0
        webhook = self.alert_cfg.get("dingtalk_webhook")
        if not webhook:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        text = f"### 🟢 机器人守护恢复\n\n- **时间**: {stamp}\n- **服务**: {service} 已恢复正常"
        dingtalk_send(webhook, self.alert_cfg.get("dingtalk_secret", ""), "机器人守护恢复", text)

    # ---- 主循环 ----
    def tick(self) -> None:
        """跑一轮：检查 -> 判定 -> 重连 -> 告警/恢复。"""
        result = self.run_checks()

        # 统计各服务是否有故障 target
        service_down: dict[str, list[str]] = {}
        for target in result["fail"]:
            name, service = target["name"], target.get("service", "unknown")
            if self.fail_counts.get(name, 0) >= self.threshold:
                service_down.setdefault(service, []).append(name)

        # 恢复判定：故障 target 重新通过时清除状态
        failed_names = {t["name"] for t in result["fail"]}
        for target in result["ok"]:
            service = target.get("service", "unknown")
            if service in self.restart_state and self._service_healthy(service, result):
                logger.info("[%s] 已恢复", service)
                self.restart_state.pop(service, None)
                self.fail_counts[target["name"]] = 0
                self._notify_recover(service)

        for service, names in service_down.items():
            reason = "、".join(names)
            # 若该服务正在恢复中，先复位状态再重试
            if service in self.restart_state:
                self.restart_state[service]["attempt"] = 1
                self.restart_state[service]["next_ts"] = 0
            self.restart_service(service, reason)

    def _service_healthy(self, service: str, result: dict[str, list[dict]]) -> bool:
        """服务下所有 target 当前都通过才算恢复。"""
        relevant = [t for t in result["ok"] + result["fail"] if t.get("service") == service]
        return all(t in result["ok"] for t in relevant)

    def run(self) -> None:
        logger.info("Watchdog 启动，检查间隔 %ss，失败阈值 %d", self.interval, self.threshold)
        while True:
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - 守护进程不允许崩
                logger.exception("本轮检查异常: %s", exc)
            time.sleep(self.interval)


def setup_logging() -> None:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler = TimedRotatingFileHandler(LOG_PATH, when="midnight", backupCount=7, encoding="utf-8")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    # 控制台输出（有窗口时可见）
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)


def main() -> None:
    parser = argparse.ArgumentParser(description="NIKKE QQ 机器人链路保险系统")
    parser.add_argument("--check", "--once", action="store_true", help="只跑一轮检查后退出")
    args = parser.parse_args()

    setup_logging()
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("配置读取失败 %s: %s", CONFIG_PATH, exc)
        sys.exit(1)

    watchdog = Watchdog(config)
    if args.check:
        result = watchdog.run_checks()
        for target in watchdog.targets:
            status = "OK " if target in result["ok"] else "FAIL"
            count = watchdog.fail_counts.get(target["name"], 0)
            print(f"{status}  {target['name']:<16} (连续失败 {count})")
        print(f"总结: {len(result['ok'])}/{len(watchdog.targets)} 项正常")
        sys.exit(0 if not result["fail"] else 2)

    watchdog.run()


if __name__ == "__main__":
    main()
