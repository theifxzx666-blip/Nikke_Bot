from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from manager import manager


class ManagerTests(unittest.TestCase):
    def test_default_config_and_rejects_invalid_import(self) -> None:
        self.assertEqual(manager.validate_config(manager.DEFAULT_CONFIG), (True, ""))
        valid, message = manager.validate_config({"check_interval": 0, "skills": []})
        self.assertFalse(valid)
        self.assertIn("check_interval", message)
        valid, message = manager.validate_config({"skills": [{"name": "重复"}, {"name": "重复"}]})
        self.assertFalse(valid)
        self.assertIn("重复", message)

    def test_dingtalk_signature(self) -> None:
        timestamp = "1700000000000"
        secret = "SEC-test"
        digest = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}\n{secret}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected = urllib.parse.quote_plus(base64.b64encode(digest))
        self.assertEqual(manager.dingtalk_sign(timestamp, secret), expected)

    def test_wait_service_ready_uses_health_check(self) -> None:
        with mock.patch.object(manager, "check_service", side_effect=[(False, "等待"), (True, "就绪")]), \
             mock.patch.object(manager.time, "sleep"):
            self.assertTrue(manager.wait_service_ready("bridge", timeout=2))

    def test_manual_stop_pauses_guard_until_start(self) -> None:
        manager.Handler._set_guard_state("astrbot", False)
        self.assertIn("astrbot", manager._guard_paused)
        manager.Handler._set_guard_state("astrbot", True)
        self.assertNotIn("astrbot", manager._guard_paused)

    def test_http_static_and_api_routes(self) -> None:
        manager._config = json.loads(json.dumps(manager.DEFAULT_CONFIG))
        manager._status.clear()
        server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(base + "/web/index.html", timeout=3) as response:
                html = response.read().decode("utf-8")
            self.assertIn("NIKKE 机器人管理", html)

            with urllib.request.urlopen(base + "/api/status", timeout=3) as response:
                status = json.load(response)
            self.assertIn("astrbot", status["services"])
            self.assertFalse(status["services"]["onebot"]["controllable"])
            self.assertFalse(status["services"]["astrbot"]["guarded"])

            request = urllib.request.Request(
                base + "/api/export",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                exported = json.load(response)
            self.assertIn("skills", exported["config"])

            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + "/web/../manager.py", timeout=3)
            self.assertIn(caught.exception.code, {403, 404})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_start_http_skips_an_occupied_port(self) -> None:
        # 单实例模式：默认端口已被监听即视为已有实例，start_http 返回 None（不再顺延开新实例）
        occupied = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
        occupied_thread = threading.Thread(target=occupied.serve_forever, daemon=True)
        occupied_thread.start()
        original_port = manager.HTTP_PORT
        try:
            manager.HTTP_PORT = occupied.server_port
            started = manager.start_http()
            self.assertIsNone(started, "端口被占时单实例模式应返回 None")
        finally:
            occupied.shutdown()
            occupied.server_close()
            occupied_thread.join(timeout=3)
            manager.HTTP_PORT = original_port


if __name__ == "__main__":
    unittest.main()
