# -*- coding: utf-8 -*-
"""NIKKE QQ 机器人管理客户端（manager.py）

功能：一键启动 / 后台集成 / 技能管理 / 运维监控(检测+自动重启+钉钉告警) / 配置导出导入
技术：Python 标准库 http.server + pywebview（内嵌 WebView2，不依赖外部浏览器）
用法：python manager.py [--no-webview]    # --no-webview 仅起服务便于调试
打包：pyinstaller --onefile --noconsole --name NIKKE_Manager --add-data "web;web" --hidden-import webview.platforms.edgechromium manager.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import psutil  # 进程/连接检测：纯 Python，无外部命令，避免 cmd 弹窗

BASE_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent)
PROJECT_ROOT = BASE_DIR.parent
WEB_DIR = (Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "web") if getattr(sys, "frozen", False) else BASE_DIR / "web"
BG_DIR = BASE_DIR / "manager_bg"
CONFIG_PATH = BASE_DIR / "manager_config.json"
LOG_PATH = BASE_DIR / "manager.log"
BG_FILE = BG_DIR / "bg.png"
LOGS_DIR = BASE_DIR / "manager_logs"        # 服务静默启动后的日志落地目录
QRCODE_PATH = PROJECT_ROOT / "supports" / "NapCat.Shell.Windows.OneKey" / "cache" / "qrcode.png"  # NapCat 扫码二维码
INSTALL_BAT = PROJECT_ROOT / "qq_bot" / "01-install-env.bat"  # 首次依赖安装脚本
HTTP_PORT = int(os.environ.get("NIKKE_MANAGER_PORT", "8899"))

# 静默启动：CREATE_NO_WINDOW，服务不弹 cmd 窗口；日志通过 stdout/stderr 重定向到文件
SILENT_FLAG = 0x08000000 if os.name == "nt" else 0
CREATE_NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0  # 保留，仅作参考

logger = logging.getLogger("nikke-manager")

# ---------------- 默认配置 ----------------
DEFAULT_CONFIG = {
    "daemon_enabled": True,
    "check_interval": 10,
    "fail_threshold": 3,
    "retry": {"max_attempts": 3, "backoff_seconds": [30, 60, 120]},
    "alert": {
        "dingtalk_webhook": "",
        "dingtalk_secret": "",
        "cooldown_minutes": 30,
        "notify_on_recover": True,
    },
    "background": {"type": "gradient", "data": ""},
    "skills": [
        {"name": "词条导入", "desc": "引导截图导入装备词条", "command": "#词条导入", "enabled": True},
        {"name": "词条统计", "desc": "统计并渲染词条卡片/对比", "command": "#词条统计", "enabled": True},
        {"name": "词条导出", "desc": "导出词条 Excel", "command": "#词条导出", "enabled": True},
        {"name": "角色查询", "desc": "本地角色卡查询", "command": "#角色", "enabled": True},
        {"name": "Wiki 查询", "desc": "在线 wiki 兜底查询", "command": "#wiki", "enabled": True},
        {"name": "养成建议", "desc": "角色培养建议", "command": "#养成", "enabled": True},
    ],
}

# ---------------- 服务定义 ----------------
SERVICES = {
    "astrbot": {
        "label": "AstrBot",
        "kind": "tcp",
        "port": 6185,
        "url": "http://127.0.0.1:6185",
        "start": {"cmd": ["cmd", "/c", "start-astrbot.bat"], "cwd": PROJECT_ROOT / "supports" / "AstrBot"},
        "wait_port": 6185,
        "wait_seconds": 40,
    },
    "napcat": {
        "label": "NapCat",
        "kind": "port_or_process",
        "port": 6099,
        "process": "NapCatWinBootMain.exe",
        "url": "http://127.0.0.1:6099",
        "start": {"cmd": ["cmd", "/c", "launcher-win10.bat"], "cwd": PROJECT_ROOT / "supports" / "NapCat.Shell.Windows.OneKey"},
        "wait_port": 6099,
        "wait_seconds": 25,
        # 注意：QQ.exe 不可按名全杀（会误杀用户自己登录的 QQ）。napcat 的停止
        # 走 stop_service 特判的 kill_napcat_tree()（进程树，只杀机器人账号 QQ）。
        "stop_processes": ["NapCatWinBootMain.exe"],
    },
    "bridge": {
        "label": "会战桥接",
        "kind": "http",
        "url": "http://127.0.0.1:8793/health",
        "expect_ok": True,
        "start": {"cmd": ["cmd", "/c", "start-astrbot-bridge.bat"], "cwd": PROJECT_ROOT / "qq_bot"},
        "wait_http": "http://127.0.0.1:8793/health",
        "wait_seconds": 20,
        "stop_port": 8793,
    },
    "admin": {
        "label": "成员后台",
        "kind": "tcp",
        "port": 8788,
        "url": "http://127.0.0.1:8788",
        "start": {"cmd": ["cmd", "/c", "02-start-qq-bot.bat"], "cwd": PROJECT_ROOT / "qq_bot"},
        "wait_port": 8788,
        "wait_seconds": 20,
        "stop_port": 8788,
    },
    "onebot": {
        "label": "OneBot 链路",
        "kind": "tcp_established",
        "port": 6199,
        "url": "",
        "start": None,          # 链路故障归因到 napcat 重启
        "restart_owner": "napcat",
    },
}

# 停止 AstrBot 时按端口杀，避免误杀管理端自身
for _svc in ("astrbot",):
    SERVICES[_svc]["stop_port"] = SERVICES[_svc]["port"]

# ---------------- 全局状态 ----------------
_config: dict = dict(DEFAULT_CONFIG)
_status: dict[str, dict] = {}          # name -> {ok, since, fails, detail}
_events: deque = deque(maxlen=200)
_restart_state: dict[str, dict] = {}   # service -> {attempt, next_ts}
_alert_ts: dict[str, float] = {}
_recovered_ts: dict[str, float] = {}
_guard_paused: set[str] = set()
_daemon_running = False
_lock = threading.Lock()
_config_lock = threading.RLock()


# ---------------- 日志 ----------------
def setup_logging() -> None:
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler = TimedRotatingFileHandler(LOG_PATH, when="midnight", backupCount=7, encoding="utf-8")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)


# ---------------- 配置 ----------------
def load_config() -> dict:
    global _config
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            _deep_merge(cfg, saved)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("配置读取失败，使用默认: %s", exc)
    _config = cfg
    return cfg


def validate_config(candidate: object) -> tuple[bool, str]:
    if not isinstance(candidate, dict):
        return False, "配置必须是 JSON 对象"
    skills = candidate.get("skills", [])
    if not isinstance(skills, list) or any(not isinstance(item, dict) for item in skills):
        return False, "skills 必须是对象数组"
    names: set[str] = set()
    for item in skills:
        name = str(item.get("name") or "").strip()
        if not name or name in names:
            return False, "技能名称不能为空或重复"
        names.add(name)
    for key in ("check_interval", "fail_threshold"):
        if key in candidate:
            try:
                if int(candidate[key]) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return False, f"{key} 必须是正整数"
    return True, ""


def _deep_merge(base: dict, extra: dict) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def save_config() -> None:
    with _config_lock:
        temp_path = CONFIG_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(_config, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(CONFIG_PATH)


# ---------------- 检测 ----------------
def check_tcp(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def check_http(url: str, expect_ok: bool = False) -> bool:
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


def _hidden_run(args: list, **kwargs):
    """隐藏窗口运行外部命令（仅作兜底；检测主体走 psutil，不弹 cmd 窗口）"""
    kwargs.setdefault("creationflags", SILENT_FLAG)
    return subprocess.run(args, **kwargs)


def read_logs_tail(n: int = 50) -> dict:
    """读取 manager.log 与 manager_logs/*.log 各文件尾部 n 行（供客户端查看日志）。"""
    files: list[Path] = [LOG_PATH]
    if LOGS_DIR.is_dir():
        files += sorted(LOGS_DIR.glob("*.log"))
    out: dict[str, list[str]] = {}
    for f in files:
        if not f.is_file():
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
            out[f.name] = lines
        except OSError:
            continue
    return out


def system_install_deps() -> tuple[bool, str]:
    """静默执行首次依赖安装（qq_bot/01-install-env.bat），输出重定向到 manager_logs/install.log。"""
    if not INSTALL_BAT.is_file():
        return False, f"未找到安装脚本: {INSTALL_BAT}"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(LOGS_DIR / "install.log", "ab")
    try:
        subprocess.Popen(
            [str(INSTALL_BAT)],
            cwd=str(INSTALL_BAT.parent),
            creationflags=SILENT_FLAG,
            stdout=logf,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
        return True, "已静默启动依赖安装，日志: install.log"
    except OSError as exc:
        return False, f"启动安装失败: {exc}"


def check_tcp_established(port: int) -> bool:
    """OneBot 链路检测：6199 是否有 ESTABLISHED 连接（psutil 纯 Python）"""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status == "ESTABLISHED":
                return True
        return False
    except (psutil.Error, PermissionError, OSError):
        return False


def check_process(name: str) -> bool:
    """进程存在检测（psutil 纯 Python，替代 tasklist）"""
    try:
        target = name.lower()
        for proc in psutil.process_iter(["name"]):
            pname = proc.info.get("name")
            if pname and pname.lower() == target:
                return True
        return False
    except (psutil.Error, OSError):
        return False


def check_service(svc: dict) -> tuple[bool, str]:
    """返回 (是否健康, 详情)"""
    kind = svc.get("kind")
    if kind == "tcp":
        return (check_tcp(svc["port"]), f"端口 {svc['port']}")
    if kind == "port_or_process":
        ok = check_process(svc["process"]) or check_tcp(svc["port"])
        return (ok, f"进程/端口 {svc['port']}")
    if kind == "http":
        ok = check_http(svc["url"], svc.get("expect_ok"))
        return (ok, "HTTP 健康")
    if kind == "tcp_established":
        ok = check_tcp_established(svc["port"])
        return (ok, f"链路 {svc['port']}")
    return (False, "未知类型")


def wait_service_ready(name: str, timeout: float | None = None) -> bool:
    """启动后等待服务实际可用，避免界面在进程刚创建时误报成功。"""
    svc = SERVICES.get(name)
    if not svc:
        return False
    deadline = time.monotonic() + float(timeout if timeout is not None else svc.get("wait_seconds", 20))
    while time.monotonic() < deadline:
        ok, _ = check_service(svc)
        if ok:
            return True
        time.sleep(0.7)
    return False


# ---------------- 进程/服务控制 ----------------
def kill_port(port: int) -> bool:
    """按端口杀掉监听进程（psutil 纯 Python，不弹窗；不碰无关 python 进程）"""
    killed = False
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN":
                pid = conn.pid
                if pid and pid > 4:
                    try:
                        psutil.Process(pid).kill()
                        killed = True
                    except psutil.Error:
                        pass
    except (psutil.Error, PermissionError, OSError):
        pass
    return killed


def kill_process(name: str) -> bool:
    """按进程名结束进程（psutil 纯 Python，不弹窗）"""
    killed = False
    try:
        target = name.lower()
        for proc in psutil.process_iter(["name", "pid"]):
            pname = proc.info.get("name")
            if pname and pname.lower() == target:
                try:
                    proc.kill()
                    killed = True
                except psutil.Error:
                    pass
    except psutil.Error:
        pass
    return killed


def kill_napcat_tree() -> bool:
    """精准停止 NapCat：只杀 NapCatWinBootMain 及其拉起的进程树（含机器人账号的 QQ.exe），
    绝不按 QQ.exe 进程名全杀——用户自己登录的 QQ 账号进程不受影响。

    - 机器人账号的 QQ 由 launcher-win10.bat 通过 NapCatWinBootMain.exe 拉起，是其子进程；
    - 先收集 NapCatWinBootMain 的递归子进程 PID（含机器人 QQ），再杀 NapCatWinBootMain 自身；
    - 兜底：若 NapCatWinBootMain 已退出但残留 QQ.exe（reparent 到其他父进程），
      仅当该 QQ.exe 的父进程链中出现过 NapCatWinBootMain.exe 时才击杀。
    """
    killed = False
    qq_pids: set[int] = set()
    napcat_procs: list = []

    def _name(p: psutil.Process) -> str:
        try:
            return (p.info.get("name") or "").lower() if isinstance(p.info, dict) else (p.name() or "").lower()
        except psutil.Error:
            return ""

    # 1) 收集 NapCatWinBootMain 及其递归子进程（含机器人 QQ.exe）
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if _name(proc) == "napcatwinbootmain.exe":
                napcat_procs.append(proc)
                for child in proc.children(recursive=True):
                    qq_pids.add(child.pid)  # children() 返回 psutil.Process，用 .pid（无 .info）
        except psutil.Error:
            pass

    # 2) 兜底：NapCat 已退出但残留机器人 QQ——按父进程链识别（reparent 兜底）
    if not napcat_procs:
        for proc in psutil.process_iter(["pid", "name"]):
            if _name(proc) != "qq.exe":
                continue
            try:
                p = proc
                seen: set[int] = set()
                while p and p.pid not in seen:
                    seen.add(p.pid)
                    ppid = p.ppid()
                    if ppid <= 0:
                        break
                    p = psutil.Process(ppid)
                    if _name(p) == "napcatwinbootmain.exe":
                        qq_pids.add(proc.info["pid"])
                        break
            except psutil.Error:
                pass

    # 3) 先杀 NapCatWinBootMain 进程树，再兜底杀收集到的 QQ
    for proc in napcat_procs:
        try:
            proc.kill()
            killed = True
        except psutil.Error:
            pass
    for pid in qq_pids:
        try:
            psutil.Process(pid).kill()
            killed = True
        except psutil.Error:
            pass
    return killed


def _refresh_status(name: str) -> None:
    """手动启停后立即刷新该服务状态缓存（守护暂停时尤为重要）"""
    svc = SERVICES.get(name)
    if not svc:
        return
    ok, detail = check_service(svc)
    with _lock:
        st = _status.setdefault(name, {"ok": True, "since": time.time(), "fails": 0, "detail": detail})
        st["ok"] = ok
        st["detail"] = detail
        if ok:
            st["fails"] = 0


def _refresh_all_status() -> None:
    """刷新所有服务状态（含 onebot 链路），手动操作后保证前端一致"""
    for name in list(SERVICES):
        _refresh_status(name)


def start_service(name: str, wait: bool = True, progress: object = None) -> bool:
    svc = SERVICES.get(name)
    if not svc or not svc.get("start"):
        return False
    spec = svc["start"]
    if progress:
        progress(f"正在启动 {svc['label']}，发出启动指令 ...")
    try:
        # 静默启动：不弹 cmd 窗口，stdout/stderr 重定向到 manager_logs/<name>.log
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOGS_DIR / f"{name}.log"
        with log_path.open("ab") as logf:
            subprocess.Popen(
                spec["cmd"],
                cwd=str(spec["cwd"]),
                creationflags=SILENT_FLAG,
                stdout=logf,
                stderr=logf,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        _add_event("start", name, f"已静默启动 {spec['cmd'][-1]}，日志: {log_path.name}" + ("，等待就绪" if wait else ""))
        logger.info("start %s: %s", name, spec["cmd"])
        if progress:
            progress(f"已发出启动指令 {spec['cmd'][-1]}，等待服务就绪 ...")
        # 守护自动重启时 wait=False：不阻塞守护主循环，就绪状态交给后续轮询更新
        if not wait:
            _refresh_status(name)
            if progress:
                progress(f"{svc['label']} 启动指令已发出（后台继续拉起）")
            return True
        ready = wait_service_ready(name)
        if progress:
            progress("服务已就绪" if ready else "等待超时，服务未就绪")
        if ready:
            _add_event("start", name, "服务已就绪")
            _refresh_status(name)
            return True
        _add_event("error", name, "启动命令已发出，但在等待时间内未就绪")
        _refresh_status(name)
        return False
    except OSError as exc:
        _add_event("error", name, f"启动失败: {exc}")
        logger.error("start %s 失败: %s", name, exc)
        if progress:
            progress(f"启动失败: {exc}")
        return False


def stop_service(name: str, progress: object = None) -> bool:
    svc = SERVICES.get(name)
    if not svc:
        return False
    if progress:
        progress(f"正在停止 {svc['label']} ...")
    stopped = False
    if name == "napcat":
        # 精准停止：只杀 NapCat 进程树（含机器人账号 QQ），不误杀用户自己登录的 QQ
        stopped = kill_napcat_tree()
    for proc in svc.get("stop_processes", []):
        stopped = kill_process(proc) or stopped
    port = svc.get("stop_port")
    if port:
        stopped = kill_port(port) or stopped
    if progress:
        progress("正在检测是否有残余进程 ...")
    # kill 是异步的：等待进程真正退出（最多 8 秒），确保状态刷新准确
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not check_service(svc)[0]:
            break
        time.sleep(0.5)
    if check_service(svc)[0]:
        _add_event("error", name, "停止后服务仍在运行（进程未完全退出，可能需要强制结束）")
        if progress:
            progress("仍有进程未完全退出")
    else:
        _add_event("stop", name, "已停止")
        if progress:
            progress("已全部关闭")
    logger.info("stop %s", name)
    _refresh_status(name)
    return stopped


def restart_service(name: str, reason: str = "手动", wait: bool = True, progress: object = None) -> bool:
    if progress:
        progress(f"正在重启 {SERVICES.get(name, {}).get('label', name)} ...")
    stop_service(name, progress=progress)
    time.sleep(1)
    return start_service(name, wait=wait, progress=progress)


# ---------------- 任务进度（启停操作流式上报） ----------------
# task_id -> {"messages": [...], "done": bool, "ok": bool}
_tasks: dict[str, dict] = {}
_task_seq = 0
MAX_TASKS = 30  # 只保留最近 30 个任务


def _make_task() -> str:
    global _task_seq
    with _lock:
        _task_seq += 1
        tid = f"t{int(time.time())}_{_task_seq}"
        _tasks[tid] = {"messages": [], "done": False, "ok": True}
        # 清理过旧任务，防止内存膨胀
        while len(_tasks) > MAX_TASKS:
            oldest = next(iter(_tasks))
            if _tasks[oldest].get("done"):
                del _tasks[oldest]
            else:
                break
        return tid


def _task_log(tid: str, msg: str) -> None:
    with _lock:
        t = _tasks.get(tid)
        if t:
            t["messages"].append(msg)


def _task_finish(tid: str, ok: bool) -> None:
    with _lock:
        t = _tasks.get(tid)
        if t:
            t["done"] = True
            t["ok"] = ok


# ---------------- 事件 ----------------
def _add_event(kind: str, service: str, message: str) -> None:
    event = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": kind,
        "service": service,
        "message": message,
    }
    with _lock:
        _events.appendleft(event)


# ---------------- 钉钉 ----------------
def dingtalk_sign(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256,
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code))


def dingtalk_send(webhook: str, secret: str, title: str, text: str) -> bool:
    if not webhook:
        return False
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
            return result.get("errcode") == 0
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning("钉钉发送失败: %s", exc)
        return False


def _alert_if_needed(service: str, reason: str, detail: str) -> None:
    alert = _config.get("alert", {})
    now = time.time()
    cooldown = float(alert.get("cooldown_minutes", 30)) * 60
    if now - _alert_ts.get(service, 0) < cooldown:
        return
    _alert_ts[service] = now
    _recovered_ts[service] = now
    text = (
        f"### 🔴 机器人守护告警\n\n"
        f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **服务**: {service}（{reason}）\n"
        f"- **详情**: {detail}\n"
        f"- **建议**: 检查对应服务窗口/日志"
    )
    if dingtalk_send(alert.get("dingtalk_webhook", ""), alert.get("dingtalk_secret", ""), "机器人守护告警", text):
        _add_event("alert", service, detail)
        logger.warning("[%s] 钉钉告警已发送", service)


def _notify_recover(service: str) -> None:
    alert = _config.get("alert", {})
    if not alert.get("notify_on_recover"):
        return
    now = time.time()
    cooldown = float(alert.get("cooldown_minutes", 30)) * 60
    if now - _recovered_ts.get(service, 0) >= cooldown:
        return
    _recovered_ts[service] = 0
    text = (
        f"### 🟢 机器人守护恢复\n\n"
        f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **服务**: {service} 已恢复正常"
    )
    if dingtalk_send(alert.get("dingtalk_webhook", ""), alert.get("dingtalk_secret", ""), "机器人守护恢复", text):
        _add_event("recover", service, "已恢复正常")


# ---------------- 守护线程 ----------------
def daemon_tick() -> None:
    result = {}
    for name, svc in SERVICES.items():
        ok, detail = check_service(svc)
        with _lock:
            st = _status.setdefault(name, {"ok": True, "since": time.time(), "fails": 0, "detail": detail})
            if ok:
                st["fails"] = 0
                st["ok"] = True
                st["detail"] = detail
            else:
                st["fails"] = st.get("fails", 0) + 1
                st["detail"] = detail
                # 达到阈值触发重启
                if st["fails"] >= _config.get("fail_threshold", 2):
                    result[name] = st["fails"]

    for name, fails in result.items():
        svc = SERVICES[name]
        owner = svc.get("restart_owner", name)
        if owner in _guard_paused:
            continue
        now = time.time()
        state = _restart_state.get(owner)
        if state and state.get("next_ts", 0) > now:
            continue
        retry = _config.get("retry", {})
        max_attempts = int(retry.get("max_attempts", 3))
        backoff = [float(x) for x in retry.get("backoff_seconds", [10, 30, 60])]
        attempt = (state.get("attempt", 0) + 1) if state else 1
        if attempt > max_attempts:
            _alert_if_needed(owner, svc["label"], f"连续失败 {fails} 次，重连 {max_attempts} 次仍失败")
            _restart_state[owner] = {"attempt": 1, "next_ts": now + float(_config.get("alert", {}).get("cooldown_minutes", 30)) * 60}
            continue
        delay = backoff[min(attempt - 1, len(backoff) - 1)]
        logger.warning("[%s] 故障，第 %d 次重启", owner, attempt)
        _add_event("restart", owner, f"故障自动重启（第 {attempt} 次）")
        restart_service(owner, f"故障自动重启（第 {attempt} 次）", wait=False)
        _restart_state[owner] = {"attempt": attempt, "next_ts": now + delay}

    # 恢复判定：服务恢复后清理重启状态并通知
    for owner in list(_restart_state):
        related = [
            (name, svc) for name, svc in SERVICES.items()
            if svc.get("restart_owner", name) == owner or name == owner
        ]
        checks = [(name, *check_service(svc)) for name, svc in related]
        if checks and all(ok for _, ok, _ in checks):
            with _lock:
                for name, _, detail in checks:
                    _status[name].update({"ok": True, "fails": 0, "detail": detail})
            _restart_state.pop(owner, None)
            _notify_recover(owner)
            logger.info("[%s] 已恢复", owner)


def daemon_loop() -> None:
    global _daemon_running
    _daemon_running = True
    logger.info("守护线程启动，间隔 %ss", _config.get("check_interval", 10))
    while _daemon_running:
        try:
            # 守护开关：关闭时仅保留线程存活（前端可看到状态/手动操作），不自动检测重启
            if _config.get("daemon_enabled", True):
                daemon_tick()
        except Exception as exc:  # noqa: BLE001
            logger.exception("守护 tick 异常: %s", exc)
        time.sleep(float(_config.get("check_interval", 10)))


# ---------------- HTTP ----------------
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---- 工具 ----
    def _send_json(self, data: dict, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 12 * 1024 * 1024:
            return {"__error__": "请求内容超过 12 MB"}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    def _serve_static(self, path: str) -> None:
        rel = path
        if rel in ("", "/"):
            rel = "index.html"
        target = (WEB_DIR / rel).resolve()
        # 防目录穿越
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(target.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- 路由 ----
    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/web", "/web/"):
            self.send_response(302)
            self.send_header("Location", "/web/index.html")
            self.end_headers()
            return
        if path == "/bg":
            if _config.get("background", {}).get("type") == "image" and BG_FILE.is_file():
                body = BG_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)
            return
        if path.startswith("/web/"):
            self._serve_static(path[5:])
            return
        if path == "/api/status":
            with _lock:
                items = {}
                for name, svc in SERVICES.items():
                    st = _status.get(name, {})
                    state_ok = st.get("ok") if "ok" in st else None
                    items[name] = {
                        "label": svc["label"],
                        "ok": state_ok,
                        "since": st.get("since"),
                        "fails": st.get("fails", 0),
                        "detail": st.get("detail", ""),
                        "url": svc.get("url", ""),
                        "controllable": bool(svc.get("start")),
                        "guarded": _daemon_running and svc.get("restart_owner", name) not in _guard_paused,
                    }
            self._send_json({"daemon": _daemon_running and bool(_config.get("daemon_enabled", True)), "services": items})
            return
        if path == "/api/skills":
            self._send_json({"skills": _config.get("skills", [])})
            return
        if path == "/api/events":
            with _lock:
                events = list(_events)
            self._send_json({"events": events})
            return
        if path == "/api/settings":
            self._send_json(_config)
            return
        if path == "/api/export":
            self._send_json({"config": _config})
            return
        if path == "/api/qrcode/status":
            # NapCat 扫码登录二维码状态
            import datetime as _dt
            info = {
                "exists": QRCODE_PATH.is_file(),
                "mtime": None,
                "mtime_text": "",
            }
            if QRCODE_PATH.is_file():
                ts = QRCODE_PATH.stat().st_mtime
                info["mtime"] = ts
                info["mtime_text"] = _dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            self._send_json(info)
            return
        if path == "/api/qrcode/image":
            # 返回二维码图片（供客户端弹窗展示）
            if QRCODE_PATH.is_file():
                body = QRCODE_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404, "二维码尚未生成")
            return
        if path == "/api/system/logs":
            self._send_json({"logs": read_logs_tail(50)})
            return
        if path.startswith("/api/tasks/"):
            tid = urllib.parse.unquote(path.split("/")[-1])
            with _lock:
                t = _tasks.get(tid)
            if not t:
                self._send_json({"ok": False, "message": "任务不存在或已过期"}, 404)
                return
            self._send_json({
                "messages": list(t["messages"]),
                "done": t["done"],
                "ok": t["ok"],
            })
            return
        self.send_error(404)

    def do_POST(self) -> None:
        global _config
        path = urllib.parse.urlparse(self.path).path
        body = self._read_body()
        if "__error__" in body:
            self._send_json({"ok": False, "message": body["__error__"]}, 413)
            return

        if path == "/api/services/start":
            name = body.get("service", "all")
            self._svc_action(name, "start")
            return
        if path == "/api/services/stop":
            name = body.get("service", "all")
            self._svc_action(name, "stop")
            return
        if path == "/api/services/restart":
            name = body.get("service", "all")
            self._svc_action(name, "restart")
            return
        if path == "/api/skills":
            name = str(body.get("name") or "").strip()
            if not name:
                self._send_json({"ok": False, "message": "技能名不能为空"}, 400)
                return
            skills = _config.setdefault("skills", [])
            if any(s.get("name") == name for s in skills):
                self._send_json({"ok": False, "message": "技能已存在"}, 400)
                return
            skills.append({
                "name": name,
                "desc": str(body.get("desc") or ""),
                "command": str(body.get("command") or ""),
                "enabled": bool(body.get("enabled", True)),
            })
            save_config()
            _add_event("skill", name, "已添加技能")
            self._send_json({"ok": True})
            return
        if path == "/api/export":
            self._send_json({"config": _config})
            return
        if path == "/api/background":
            self._handle_background(body)
            return
        if path == "/api/import":
            cfg = body.get("config")
            valid, message = validate_config(cfg)
            if not valid:
                self._send_json({"ok": False, "message": message}, 400)
                return
            _config = json.loads(json.dumps(DEFAULT_CONFIG))
            _deep_merge(_config, cfg)
            save_config()
            _add_event("config", "-", "已导入配置")
            self._send_json({"ok": True})
            return
        if path == "/api/reset":
            _config = json.loads(json.dumps(DEFAULT_CONFIG))
            save_config()
            self._send_json({"ok": True})
            return
        if path == "/api/system/install_deps":
            ok, message = system_install_deps()
            self._send_json({"ok": ok, "message": message})
            return
        if path == "/api/open_browser":
            webbrowser.open(f"http://127.0.0.1:{HTTP_PORT}")
            self._send_json({"ok": True})
            return
        if path == "/api/open_service":
            name = str(body.get("service") or "")
            url = SERVICES.get(name, {}).get("url", "")
            if not url:
                self._send_json({"ok": False, "message": "该服务没有管理后台"}, 400)
                return
            webbrowser.open(url)
            self._send_json({"ok": True})
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        global _config
        path = urllib.parse.urlparse(self.path).path
        body = self._read_body()
        m = re.match(r"^/api/skills/(.+)$", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            skills = _config.setdefault("skills", [])
            for s in skills:
                if s.get("name") == name:
                    if "enabled" in body:
                        s["enabled"] = bool(body["enabled"])
                    if "desc" in body:
                        s["desc"] = str(body["desc"])
                    if "command" in body:
                        s["command"] = str(body["command"])
                    save_config()
                    _add_event("skill", name, "开关更新: " + str(s["enabled"]))
                    self._send_json({"ok": True})
                    return
            self._send_json({"ok": False, "message": "技能不存在"}, 404)
            return
        if path == "/api/settings":
            candidate = json.loads(json.dumps(_config))
            for key in ("daemon_enabled", "check_interval", "fail_threshold", "retry", "alert", "background"):
                if key in body:
                    candidate[key] = body[key]
            valid, message = validate_config(candidate)
            if not valid:
                self._send_json({"ok": False, "message": message}, 400)
                return
            _config = candidate
            save_config()
            self._send_json({"ok": True})
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        m = re.match(r"^/api/skills/(.+)$", path)
        if m:
            name = urllib.parse.unquote(m.group(1))
            skills = _config.setdefault("skills", [])
            for s in skills:
                if s.get("name") == name:
                    skills.remove(s)
                    save_config()
                    _add_event("skill", name, "已删除技能")
                    self._send_json({"ok": True})
                    return
            self._send_json({"ok": False, "message": "技能不存在"}, 404)
            return
        self.send_error(404)

    # ---- 动作 ----
    def _svc_action(self, name: str, action: str) -> None:
        """启停/重启服务。改为后台任务执行：立即返回 task_id，进度通过 /api/tasks/<id> 流式获取。"""
        action_zh = {"start": "启动", "stop": "关闭", "restart": "重启"}.get(action, action)
        if name == "all":
            order = ["napcat", "astrbot", "bridge", "admin"]
            if action == "stop":
                order = list(reversed(order))

            def _worker_all(tid: str) -> None:
                results = {}
                for n in order:
                    self._set_guard_state(n, action != "stop")
                    label = SERVICES[n]["label"]
                    _task_log(tid, f"正在{action_zh} {label} ...")
                    try:
                        if action == "start":
                            results[n] = start_service(n, progress=lambda m, _n=n: _task_log(tid, m))
                        elif action == "stop":
                            results[n] = stop_service(n, progress=lambda m, _n=n: _task_log(tid, m))
                        else:
                            results[n] = restart_service(n, progress=lambda m, _n=n: _task_log(tid, m))
                    except Exception as exc:  # noqa: BLE001
                        results[n] = False
                        _task_log(tid, f"{label} 操作异常: {exc}")
                    _task_log(tid, f"{label} {action_zh}完成" if results[n] else f"{label} {action_zh}失败")
                _task_log(tid, "正在刷新服务状态 ...")
                _refresh_all_status()  # 模块级函数，Handler 无此方法
                _task_log(tid, "已全部完成")
                _task_finish(tid, all(results.values()))

            tid = _make_task()
            threading.Thread(target=_worker_all, args=(tid,), daemon=True).start()
            self._send_json({"ok": True, "task_id": tid})
            return
        if name not in SERVICES:
            self._send_json({"ok": False, "message": "未知服务"}, 400)
            return

        def _worker_single(tid: str) -> None:
            self._set_guard_state(name, action != "stop")
            try:
                if action == "start":
                    ok = start_service(name, progress=lambda m: _task_log(tid, m))
                elif action == "stop":
                    ok = stop_service(name, progress=lambda m: _task_log(tid, m))
                else:
                    ok = restart_service(name, progress=lambda m: _task_log(tid, m))
            except Exception as exc:  # noqa: BLE001
                ok = False
                _task_log(tid, f"操作异常: {exc}")
            _task_log(tid, "正在刷新服务状态 ...")
            _refresh_all_status()  # 模块级函数，Handler 无此方法
            _task_log(tid, "操作完成" if ok else "操作失败")
            _task_finish(tid, ok)

        tid = _make_task()
        threading.Thread(target=_worker_single, args=(tid,), daemon=True).start()
        self._send_json({"ok": True, "task_id": tid})

    @staticmethod
    def _set_guard_state(name: str, enabled: bool) -> None:
        owner = SERVICES.get(name, {}).get("restart_owner", name)
        if enabled:
            _guard_paused.discard(owner)
        else:
            _guard_paused.add(owner)
            _restart_state.pop(owner, None)

    def _handle_background(self, body: dict) -> None:
        kind = body.get("type")
        if kind == "url":
            url = str(body.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                self._send_json({"ok": False, "message": "背景 URL 仅支持 http/https"}, 400)
                return
            _config["background"] = {"type": "url", "data": url}
            save_config()
            self._send_json({"ok": True})
            return
        if kind == "upload":
            data = body.get("data", "")
            if data.startswith("data:"):
                try:
                    raw = base64.b64decode(data.split(",", 1)[1])
                except (IndexError, ValueError):
                    self._send_json({"ok": False, "message": "图片数据无效"}, 400)
                    return
                if len(raw) > 8 * 1024 * 1024:
                    self._send_json({"ok": False, "message": "背景图片不能超过 8 MB"}, 400)
                    return
                BG_DIR.mkdir(parents=True, exist_ok=True)
                BG_FILE.write_bytes(raw)
                _config["background"] = {"type": "image", "data": ""}
                save_config()
                self._send_json({"ok": True})
                return
        if kind == "gradient":
            _config["background"] = {"type": "gradient", "data": ""}
            save_config()
            self._send_json({"ok": True})
            return
        self._send_json({"ok": False, "message": "参数错误"}, 400)


# ---------------- 入口 ----------------
def start_http() -> ThreadingHTTPServer | None:
    global HTTP_PORT
    # 单实例模式：默认端口已被监听即视为已有实例在运行，不再顺延开新实例（避免多个守护线程反复弹窗重启）
    if check_tcp(HTTP_PORT):
        logger.info("端口 %d 已有管理实例在运行，本次不重复启动", HTTP_PORT)
        return None
    server = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("HTTP 服务已启动: http://127.0.0.1:%d", HTTP_PORT)
    return server


def main() -> None:
    setup_logging()
    load_config()
    BG_DIR.mkdir(parents=True, exist_ok=True)
    server = start_http()
    if server is None:
        # 已有实例在运行：打开已有管理端后退出（不启动守护线程，避免重复重启弹窗）
        webbrowser.open(f"http://127.0.0.1:{HTTP_PORT}")
        logger.info("检测到已有管理实例，打开其页面后退出")
        return
    # 启动即做一次全量状态检测，保证守护关闭时前端也有真实状态（而非 None）
    try:
        _refresh_all_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("初始状态检测异常: %s", exc)
    if "--no-daemon" not in sys.argv:
        threading.Thread(target=daemon_loop, daemon=True).start()
    else:
        logger.info("--no-daemon 模式，不启动自动检测和重启")

    if "--no-webview" in sys.argv:
        logger.info("--no-webview 模式，仅后台服务（Ctrl+C 退出）")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            logger.info("退出")
        return

    try:
        import webview  # type: ignore
        logger.info("启动 pywebview 窗口")
        webview.create_window(
            "NIKKE 机器人管理",
            f"http://127.0.0.1:{HTTP_PORT}",
            width=1280, height=800, min_size=(1024, 700),
        )
        webview.start()
    except Exception as exc:  # noqa: BLE001 - 无 pywebview 时降级浏览器
        logger.warning("pywebview 不可用（%s），降级打开浏览器", exc)
        webbrowser.open(f"http://127.0.0.1:{HTTP_PORT}")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            logger.info("退出")


if __name__ == "__main__":
    main()
