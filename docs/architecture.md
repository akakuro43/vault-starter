# Architecture

vault-starter の全体像とデータフロー。

## システム境界

```
                          ┌─────────────────────────┐
                          │  Host AI Agent          │
                          │  (Claude Code / Hermes) │
                          │  - LLM 推論              │
                          │  - skill 呼び出し         │
                          │  - 通知ルーティング        │
                          └────────┬────────────────┘
                                   │ 呼び出し
                                   ▼
┌──────────────┐         ┌─────────────────────┐         ┌────────────────┐
│ Google Drive │ ──────► │  vault-starter      │ ──────► │ Notification   │
│ Transcripts/ │ pull    │  skills (Python)    │ notify  │ (Discord/Slack │
└──────────────┘         │  - mtg-importer     │         │  /stdout/file) │
                          │  - meeting-summarizer│         └────────────────┘
                          │  - person-enricher  │
                          │  - vault-resolver   │
                          │  - vault-sync       │
                          └──────────┬──────────┘
                                     │ read/write
                                     ▼
                          ┌──────────────────────┐
                          │  vault/ (Markdown)   │
                          │  - 00_inbox/         │
                          │  - 01_projects/      │
                          │  - 02_people/        │
                          │  - 03_companies/     │
                          │  - 04_meetings/      │
                          │  - 05_tasks/         │
                          │  - 06_knowledge/     │
                          │  - 99_system/        │
                          └──────────────────────┘
                                     │
                          ┌──────────▼───────────┐
                          │  Git remote (任意)    │
                          │  ↔ 複数マシン間同期   │
                          └──────────────────────┘
```

**重要**: skill scripts 自体は LLM API を呼びません。
議事録要約・人物観察抽出・候補推測などの推論はホストエージェント (Claude Code / Hermes 等) が担当します。
scripts は I/O (ファイル読み書き / Google Drive API / Git / 通知 sink) のみ担当する設計です。

---

## データフロー (詳細)

```
[Google Drive: MTG_Transcripts/]
        │
        │  mtg-importer/scripts/fetch_transcripts.py
        │  (cron / scheduler から定期実行)
        ▼
[vault/00_inbox/meeting_transcripts/<date>_<title>.md]
  frontmatter: { date, title, type: transcript, drive_id, ... }
        │
        │  meeting-summarizer (ホスト経由で実行)
        │  ・分類 (client/project) → classify_project.py
        │  ・議事録生成 → ホストの LLM (templates/meeting.md 参照)
        │  ・タスク化 → extract_action_items.py + create_tasks_from_actions.py
        ▼
[vault/04_meetings/<date>_<title>.md]            ← 議事録
[vault/05_tasks/T####-<slug>.md]                 ← タスク (action items から)
[vault/00_inbox/.../processed/YYYY-MM/]          ← トランスクリプト退避
        │
        │  person-enricher (ホスト経由で実行)
        │  ・観察抽出 → ホストの LLM
        │  ・プロファイル合成 → ホストの LLM
        ▼
[vault/02_people/<姓名>/observations.md]         ← 観察ログ (append)
[vault/02_people/<姓名>/<姓名>.md]               ← プロファイル更新
        │
        │  vault-resolver (cron / 定期)
        │  ・未解決 wikilink 検出 → scan_unresolved.py
        │  ・候補推測 → suggest_candidates.py + LLM 補正 (ホスト)
        ▼
[通知 sink: discord/slack/stdout/file] ← notify.py 経由
        │
        │  vault-sync (cron / 定期)
        │  ・git pull --rebase → ID 衝突修復 → git push
        ▼
[Git remote] ↔ 複数マシン間同期
```

---

## frontmatter 規約

### transcript (`vault/00_inbox/meeting_transcripts/`)

```yaml
date: YYYY-MM-DD
title: "会議タイトル"
type: transcript
source: google-drive
drive_id: <Google Drive file ID>
drive_filename: "TRANSCRIPT_..."
owner: your.name@example.com  # 任意
imported: YYYY-MM-DD
```

### meeting (`vault/04_meetings/`)

```yaml
description: 1文サマリー (句点なし、150字以内)
type: meeting
date: YYYY-MM-DD
client: "[[<company slug>]]" | "unclassified"
project: "[[<project slug>]]" | "unclassified"
participants: ["[[姓名]]", ...]
transcript: "[[<transcript filename>]]"
source: <hosting agent identifier>
generated: YYYY-MM-DD
tags: []
tasks_extracted_at: YYYY-MM-DD  # action items 抽出完了後に追記
```

### person (`vault/02_people/<姓名>/<姓名>.md`)

```yaml
description: この人物の役割・関係性の1文サマリー
type: person
name: 姓名
org: 所属組織
role: 役割・肩書き
projects: []
meeting_count: 0
last_meeting: ""
related_projects: []
updated: YYYY-MM-DD
```

### task (`vault/05_tasks/T####-<slug>.md`)

```yaml
id: T####
type: task
status: draft | todo | in-progress | done
created: YYYY-MM-DD
source_meeting: "[[<meeting filename>]]"
owner: "[[姓名]]"  # 担当者
due: YYYY-MM-DD   # 任意
```

詳細・enum 値の全体像は `vault/99_system/templates/` を参照。

---

## 各 skill の責務マトリクス

| skill | 入力 | 出力 | LLM 依存 | 通知 |
|---|---|---|---|---|
| mtg-importer | Google Drive folder | `00_inbox/meeting_transcripts/*.md` | なし | stdout |
| meeting-summarizer | `00_inbox/.../*.md` | `04_meetings/*.md` + `05_tasks/T####-*.md` | **ホスト依存** (要約・分類・owner 推論) | stdout (ホストが Discord 等へ) |
| person-enricher | `04_meetings/*.md` | `02_people/<人物>/*.md` | **ホスト依存** (観察抽出・プロファイル合成) | stdout |
| vault-resolver | vault 全体 | 通知のみ (vault は更新しない) | ホストの LLM 補正は任意 | stdout (ホストが Discord 等へ) |
| vault-sync | `vault/` (git) | git push + ID 衝突修復 | なし | **notify.py 経由** (sink 切替可) |

「ホスト依存」の skill は単独実行で動きません。ホストエージェントが SKILL.md の手順に従って scripts を順次呼び出し、LLM 推論を挟み込む必要があります。

---

## ディレクトリの役割

`vault/AGENTS.md` の「Vault 構造」と「どこに何を書くか」を参照。
