"""共通通知ライブラリ。

各 skill が結果を通知したい場合に呼ぶ薄いラッパー。
sink 種別は環境変数で切り替える:

    NOTIFICATION_SINK = discord | slack | stdout | file
    DISCORD_WEBHOOK_URL  (sink=discord 時)
    SLACK_WEBHOOK_URL    (sink=slack 時)
    NOTIFICATION_FILE_PATH  (sink=file 時、デフォルト ./logs/notifications.log)

通知失敗は握り潰す (skill 本体の処理を妨げない)。
URL は stderr に出力しない (機密漏洩防止)。

Usage:
    from _common.notify import notify
    notify("ID 衝突を 3 件修復しました")

skill scripts 自体が直接 webhook を叩くのは vault-sync の id-collision 検出のみ。
それ以外の skill は最終応答を stdout に出力し、ホスト (Hermes / Claude Code 等)
が通知 sink に流す前提。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path


def _send_webhook(url: str, message: str) -> None:
    payload = json.dumps({"content": message, "text": message}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        _ = resp.read()


def _append_file(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(message.rstrip() + "\n")


def notify(message: str) -> None:
    """環境変数で指定された sink にメッセージを送る。失敗は warn のみ。"""
    sink = os.environ.get("NOTIFICATION_SINK", "stdout").strip().lower()

    try:
        if sink == "discord":
            url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
            if not url:
                print("[WARN] NOTIFICATION_SINK=discord だが DISCORD_WEBHOOK_URL 未設定", file=sys.stderr)
                return
            _send_webhook(url, message)
        elif sink == "slack":
            url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
            if not url:
                print("[WARN] NOTIFICATION_SINK=slack だが SLACK_WEBHOOK_URL 未設定", file=sys.stderr)
                return
            _send_webhook(url, message)
        elif sink == "file":
            path = Path(os.environ.get("NOTIFICATION_FILE_PATH", "./logs/notifications.log")).expanduser()
            _append_file(path, message)
        elif sink == "stdout":
            print(message)
        else:
            print(f"[WARN] 未知の NOTIFICATION_SINK={sink} (discord|slack|stdout|file)", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] 通知失敗: {type(e).__name__}", file=sys.stderr)
