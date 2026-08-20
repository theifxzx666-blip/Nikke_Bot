# -*- coding: utf-8 -*-
"""NapCat 登录二维码监控：cache\\qrcode.png 更新时自动打开，方便手机扫码。

NapCat 的 QQ 登录二维码会写入 supports/NapCat.Shell.Windows.OneKey/cache/qrcode.png，
每次刷新（约 60 秒过期）都会更新文件时间。本脚本轮询该文件，检测到变化就用
系统默认图片查看器打开，解决 launcher 窗口内二维码太小/扫不上的问题。

用法：python qrcode_watch.py [--once]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# 相对本脚本推导：launcher/.. = 项目根；二维码位于 supports/NapCat.Shell.Windows.OneKey/cache
PROJECT_ROOT = Path(__file__).resolve().parents[1]
QR_PATH = (
    PROJECT_ROOT
    / "supports"
    / "NapCat.Shell.Windows.OneKey"
    / "cache"
    / "qrcode.png"
)
POLL_INTERVAL = 2  # 秒


def show_qrcode() -> None:
    if not QR_PATH.exists():
        print("[qrcode] 未找到二维码文件:", QR_PATH)
        return
    os.startfile(str(QR_PATH))  # Windows 默认图片查看器打开
    print("[qrcode] 已打开二维码:", QR_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="NapCat 二维码监控")
    parser.add_argument("--once", action="store_true", help="打开当前二维码后退出")
    args = parser.parse_args()

    if args.once:
        show_qrcode()
        return

    print("[qrcode] 开始监控:", QR_PATH)
    last_mtime = 0.0
    while True:
        try:
            mtime = QR_PATH.stat().st_mtime
            if mtime and mtime != last_mtime:
                last_mtime = mtime
                show_qrcode()
        except OSError:
            # 文件尚未生成/被占用，忽略继续等
            pass
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
