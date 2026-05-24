---
name: mtg-importer
description: Google Drive のトランスクリプト フォルダから会議トランスクリプトを取り込み vault/00_inbox/meeting_transcripts/ に配置する
---

# mtg-importer

## 概要

Google Drive のトランスクリプト用フォルダ (例: `MTG_Transcripts/`、Google Meet が自動保存する文字起こし) を取り込み、
frontmatter 付き Markdown として `vault/00_inbox/meeting_transcripts/` に配置するスクリプト。

下流の skill (meeting-summarizer, person-enricher) が inbox を消費する起点。

## ファイル構成

```
mtg-importer/
├── SKILL.md                       このファイル
├── scripts/
│   ├── pipeline.sh                オーケストレータ（cron 想定）
│   ├── fetch_transcripts.py       メイン処理
│   └── auth_test.py               Google Drive 認証テスト
└── transcripts_imported.json      取り込み済み Drive ID（自動生成・git 管理外）
```

## 環境変数

| 変数 | 役割 | デフォルト |
|---|---|---|
| `VAULT_PATH` | Vault のパス | `<repo>/vault` |
| `GOOGLE_DRIVE_CREDENTIALS_PATH` | OAuth credentials.json のパス | `<repo>/credentials/google-drive.json` |
| `GOOGLE_DRIVE_TOKEN_PATH` | token.json の保存先 | `<repo>/credentials/token.json` |
| `GOOGLE_DRIVE_TRANSCRIPT_FOLDER` | Drive 上のフォルダ名 | `MTG_Transcripts` |
| `GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID` | フォルダ ID 直接指定 (任意) | (未指定なら name 検索) |
| `MTG_IMPORTER_LOG` | pipeline.sh のログファイル | `<repo>/logs/mtg-importer.log` |

## 初回セットアップ

```bash
# 1. Google Cloud Console で OAuth credentials を作成し、credentials/google-drive.json に配置
# 2. 認証テスト (ブラウザが開く)
python3 skills/mtg-importer/scripts/auth_test.py
# → credentials/token.json が生成される
```

## 使い方

```bash
# 通常運用 (新規ファイルのみ取り込み)
python3 skills/mtg-importer/scripts/fetch_transcripts.py

# 既存ファイルを取り込み済みとして記録のみ (本文は取り込まない)
# ※ 初回実行時は自動でこのモード
python3 skills/mtg-importer/scripts/fetch_transcripts.py --reseed

# 全ファイル強制再取り込み (リカバリ用)
python3 skills/mtg-importer/scripts/fetch_transcripts.py --all

# pipeline.sh 経由 (cron 想定)
bash skills/mtg-importer/scripts/pipeline.sh
```

## ファイル名規約

```
TRANSCRIPT_YY.MM.DD_タイトル_owner@email
例: TRANSCRIPT_26.05.01_定例会_your.name@example.com
    TRANSCRIPT_26.05.01_社内MTG_すり合わせ_your.name@example.com
```

owner (メール) は省略可。タイトル中の `_` は許容 (メール部は ASCII のみで境界判定)。

## 出力フォーマット

```markdown
---
date: 2026-05-01
title: "定例会"
type: transcript
source: google-drive
drive_id: 1abc...
drive_filename: "TRANSCRIPT_26.05.01_定例会_your.name@example.com"
owner: your.name@example.com
imported: 2026-05-06
---

（トランスクリプト本文）
```

## 動作仕様

- 対象は指定フォルダ直下のみ。サブフォルダは走査しない
- 初回実行時は自動 seed モード (既存ファイルを記録のみ・本文取り込みなし)
- 以降の実行で、新規追加ファイルのみ取り込む
- `transcripts_imported.json` で重複取り込みを防止
- ファイル名のパース失敗時はスキップ (エラーにしない)

## スケジューリング

`pipeline.sh` を cron / launchd / Hermes 等の好きなスケジューラから定期実行してください。
例 (crontab、毎時:05):

```cron
5 * * * * /bin/bash /path/to/vault-starter/skills/mtg-importer/scripts/pipeline.sh
```

その他の例は `docs/scheduling-examples.md` を参照。
