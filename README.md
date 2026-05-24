# vault-starter

Google Meet のトランスクリプトを起点に、**議事録 / 人物プロファイル / タスク**を Obsidian Vault に自動振り分けする Python skill 群と Vault スケルトン。

## これは何か

Google Drive に溜まる会議トランスクリプトを Obsidian Vault に取り込み、

1. **議事録** (`vault/04_meetings/`) — 構造化された Markdown
2. **人物プロファイル + 観察ログ** (`vault/02_people/`) — 議事録から人物単位で抽出
3. **タスク** (`vault/05_tasks/`) — action items から起票
4. **未解決リンクの通知** (Discord / Slack / file / stdout) — 02_people や 01_projects に存在しない wikilink を検知

これらを継続的に蓄積し、過去の会議文脈を AI が引き出せる状態に保つ仕組みです。

> **配布物に LLM API key は不要です**。議事録要約・人物考察などの推論は、利用者側の **ホストエージェント** (Claude Code / Hermes 等) が担当する設計になっています。skill scripts 自体は I/O のみを担当。

## 前提環境

| 必須 | バージョン / 条件 |
|---|---|
| **Python** | 3.11+ ([uv](https://docs.astral.sh/uv/) 推奨) |
| **Obsidian** | 任意の最近のバージョン |
| **Google Drive API credentials** | OAuth 2.0 Client ID (Google Cloud Console で作成) |
| **ホストエージェント** | Claude Code または Hermes (LLM 推論を伴う skill を動かすために必要) |

| 任意 | 用途 |
|---|---|
| Discord / Slack webhook | 通知先として使う場合 |
| Git remote | vault-sync で複数マシン間同期する場合 |

## クイックスタート

```bash
# 1. clone
git clone <this-repo>.git my-vault
cd my-vault

# 2. bootstrap (uv venv + 依存インストール + .env 生成)
./bootstrap.sh

# 3. .env を編集
$EDITOR .env
# → GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID, NOTIFICATION_SINK, YOUR_EMAIL_DOMAINS 等を設定

# 4. Google Drive OAuth credentials を配置
# credentials/google-drive.json に Google Cloud Console でダウンロードした JSON を置く

# 5. Drive 認証テスト (ブラウザが開きます)
source .venv/bin/activate
python3 skills/mtg-importer/scripts/auth_test.py

# 6. 初回トランスクリプト取り込み (自動で seed モード — 既存ファイルを記録のみ、本文は取らない)
python3 skills/mtg-importer/scripts/fetch_transcripts.py

# 7. 以降は新規ファイルのみ取り込まれる
python3 skills/mtg-importer/scripts/fetch_transcripts.py
```

下流の skill (meeting-summarizer / person-enricher / vault-resolver) は LLM 推論を必要とするため、Hermes か Claude Code Routines から呼んでください。詳細は [docs/scheduling-examples.md](docs/scheduling-examples.md)。

> **スクリーンショット付きの詳細手順**は [docs/install-guide.md](docs/install-guide.md) (note 公開向けドラフト) を参照してください。

## ディレクトリ構成

```
vault-starter/
├── README.md
├── .env.example            通知 sink / Google Drive / Vault path 等
├── bootstrap.sh            初期セットアップ
├── requirements.txt        Python 依存
├── docs/
│   ├── architecture.md     データフロー / frontmatter 規約
│   ├── skills-catalog.md   5 skill の詳細仕様
│   └── scheduling-examples.md  cron / launchd / Hermes / Claude Code Routines
├── skills/
│   ├── _common/notify.py   通知 sink 抽象化 (discord/slack/stdout/file)
│   ├── mtg-importer/       Drive → Inbox
│   ├── meeting-summarizer/ Inbox → 議事録 + タスク
│   ├── person-enricher/    議事録 → 人物プロファイル
│   ├── vault-resolver/     未解決 wikilink 検出 → 通知
│   └── vault-sync/         Git 同期 + ID 衝突修復
├── vault/                  Obsidian Vault スケルトン
│   ├── AGENTS.md           方法論マニュアル (Level 2 抜粋版)
│   ├── CLAUDE.md           @AGENTS.md ラッパー
│   ├── 00_inbox/           自動取込の着地点
│   ├── 01_projects/        仕事案件
│   ├── 02_people/          人物情報 (per-person ディレクトリ)
│   ├── 03_companies/       会社・組織エンティティ
│   ├── 04_meetings/        議事録
│   ├── 05_tasks/           タスク管理
│   ├── 06_knowledge/       横断ナレッジ
│   └── 99_system/          ルール・テンプレート 8 個
├── credentials/            OAuth credentials (gitignore)
└── logs/                   通知ログ等 (gitignore)
```

## スケジューリングは利用者に委ねる

skill は単体実行可能な CLI です。Hermes / Claude Code Routines / launchd / crontab / 手動実行など、好きな方法で動かしてください。

`meeting-summarizer` と `person-enricher` は LLM 推論を必要とするので、素の cron からは完結しません。Hermes または Claude Code Routines を推奨します。

詳細: [docs/scheduling-examples.md](docs/scheduling-examples.md)

## カスタマイズポイント

| やりたいこと | どこを触る |
|---|---|
| 通知先を Discord → Slack に変更 | `.env` の `NOTIFICATION_SINK=slack` + `SLACK_WEBHOOK_URL=...` |
| Vault の場所を変える | `.env` の `VAULT_PATH=...` |
| Drive フォルダ名を変える | `.env` の `GOOGLE_DRIVE_TRANSCRIPT_FOLDER` または `..._FOLDER_ID` |
| 自分の組織名を反映 | `.env` の `YOUR_ORGANIZATIONS`, `YOUR_EMAIL_DOMAINS` |
| 議事録テンプレートをカスタマイズ | `vault/99_system/templates/meeting.md` を編集 |
| 人物プロファイルのセクション構成を変える | `skills/person-enricher/SKILL.md` の "プロファイル 10 セクション" |
| 新しい skill を追加 | `skills/<name>/SKILL.md` + `scripts/` を追加 |

## トラブルシュート

### `uv: command not found`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### `credentials file not found`

`credentials/google-drive.json` が無い。Google Cloud Console で OAuth 2.0 Client ID (Desktop アプリ) を作成 → JSON をダウンロードして配置。

### `MTG_Transcripts フォルダが見つかりません`

Google Meet が自動で文字起こしを保存するフォルダ名が `MTG_Transcripts` と異なる可能性。`.env` の `GOOGLE_DRIVE_TRANSCRIPT_FOLDER` を実際のフォルダ名に合わせる、または `GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID` で ID を直接指定。

### vault-sync で push 失敗

`vault/` が git repo になっていない、または remote 未設定。

```bash
cd vault
git init
git remote add origin <your-repo-url>
git pull origin main
```

## License

TBD (未設定)

## Acknowledgements

このリポジトリは個人の Obsidian + Hermes ベースのナレッジ管理運用から派生して作られました。ナレッジ管理方法論全体 (`vault/AGENTS.md`) は Level 2 抜粋版です。フル方法論 (Discovery-First / Atomic Notes / Processing Pipeline 等) を含めたい場合は、`vault/AGENTS.md` を自分で拡張してください。
