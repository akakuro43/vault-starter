---
name: vault-sync
description: Vault を Git remote 経由で複数マシン間で同期する。10 分ごとに `git pull --rebase` → ID 衝突検出・自動修復 → `git commit & push`
---

# vault-sync

## 概要

`./vault/` ディレクトリを Git remote 経由で複数マシン間で自動同期するスクリプト。
`git pull --rebase --autostash` → `detect_id_collisions.py` → `git commit & push` を順に実行する。

複数のマシンで同じ Vault を編集する場合 (例: デスクトップと出先のラップトップ) のために、
タスク ID の衝突 (両側で `T0123-foo.md` を同時に作成等) を検出・自動修復してから push する。

## 前提

- Vault が Git remote (GitHub / GitLab / 自前サーバ等) に対応する private repo として管理されている
- `git push` が SSH key 等で非対話で通る状態

## 環境変数

| 変数 | 役割 | デフォルト |
|---|---|---|
| `VAULT_PATH` | Vault のパス (= sync 対象の git working tree) | `<repo>/vault` |
| `VAULT_SYNC_LOG` | sync.sh のログ出力先 | `<repo>/logs/vault-sync.log` |
| `GIT_BIN` | git binary のパス | `git` (PATH 解決) |
| `NOTIFICATION_SINK` | ID 衝突検出時の通知 sink | `stdout` |

## ファイル構成

```
vault-sync/
├── SKILL.md                            このファイル
└── scripts/
    ├── sync.sh                         オーケストレータ (cron 想定)
    └── detect_id_collisions.py         ID 衝突検出・自動修復
```

## 初回セットアップ

```bash
# 実行権限を付与
chmod +x ./skills/vault-sync/scripts/sync.sh

# 動作確認 (vault/ が git repo であることが前提)
./skills/vault-sync/scripts/sync.sh
```

## スケジューラ例 (crontab)

```cron
*/10 * * * * /bin/bash /path/to/vault-starter/skills/vault-sync/scripts/sync.sh
```

その他のスケジューラ例は `docs/scheduling-examples.md` を参照。

## ログの確認

```bash
tail -f ./logs/vault-sync.log
```

## ID 衝突修復ロジック

`detect_id_collisions.py` は `vault/05_tasks/` 配下で同一タスク ID が複数ファイルに割り当てられているケースを検出し、
git author date が新しい側に suffix (`T0123a`, `T0123b`, ...) を付与してリネームする。
リネーム時に vault 全体の wikilink (`[[T0123]]`) も書き換える。

修復結果は環境変数 `NOTIFICATION_SINK` で指定された sink に通知される (discord / slack / stdout / file)。
