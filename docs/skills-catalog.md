# Skills Catalog

vault-starter 同梱の 5 つの skill。各 skill は単体で CLI として呼べる前提で、スケジューラには依存しない。

## 設計原則

- **skill scripts は LLM を直接呼ばない**。議事録要約・人物考察などの推論はホストエージェント (Claude Code / Hermes / その他) が担当する
- skill scripts の役割は: ファイル I/O、prompt 組み立て、結果パース、frontmatter / wikilink 生成、通知 sink 呼び出し
- これにより配布物に `ANTHROPIC_API_KEY` 等の LLM 認証情報は不要
- パスは環境変数 `VAULT_PATH` で切替可。デフォルトは `<repo>/vault`

---

## 一覧

| Skill | 役割 | 入力 | 出力 | ホスト依存 |
|---|---|---|---|---|
| [mtg-importer](#mtg-importer) | Drive → Inbox | Google Drive folder | `00_inbox/meeting_transcripts/*.md` | なし |
| [meeting-summarizer](#meeting-summarizer) | Inbox → 議事録 + タスク | inbox transcript | `04_meetings/*.md`, `05_tasks/*.md` | あり (要約 / 分類 / owner 推論) |
| [person-enricher](#person-enricher) | 議事録 → 人物プロファイル | `04_meetings/`, `00_inbox/.../processed/` | `02_people/<人物>/` | あり (観察抽出 / プロファイル合成) |
| [vault-resolver](#vault-resolver) | 未解決 wikilink 検出 | vault 全体 | 通知 (sink 経由) | 任意 (候補補正) |
| [vault-sync](#vault-sync) | Git 同期 + ID 衝突修復 | `vault/` (git) | git commit/push, 通知 | なし |

---

## mtg-importer

**役割**: Google Drive のトランスクリプト用フォルダから新規ファイルを取得し、Markdown frontmatter 付きで inbox に配置。

- **入力**: Google Drive folder (デフォルト名 `MTG_Transcripts` または env var `GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID`)
- **出力**: `vault/00_inbox/meeting_transcripts/<date>_<title>.md`
- **前提**: OAuth credentials (`credentials/google-drive.json`)
- **実行**:

```bash
python3 skills/mtg-importer/scripts/fetch_transcripts.py
# 強制再取り込み
python3 skills/mtg-importer/scripts/fetch_transcripts.py --all
```

- **推奨頻度**: 毎時 (Drive にトランスクリプトが到着するタイミング次第)
- **冪等性**: `transcripts_imported.json` で重複防止。初回は自動 seed (記録のみ)

詳細: [`skills/mtg-importer/SKILL.md`](../skills/mtg-importer/SKILL.md)

---

## meeting-summarizer

**役割**: 未処理トランスクリプトを構造化議事録に変換し、action items をタスクとして起票。

- **入力**: `vault/00_inbox/meeting_transcripts/` 直下の `type: transcript` ファイル
- **出力**:
  - `vault/04_meetings/<date>_<title>.md` (議事録)
  - `vault/05_tasks/T####-<slug>.md` (action items から起票)
  - `vault/00_inbox/meeting_transcripts/processed/YYYY-MM/<date>_<title>.md` (退避)
- **前提**:
  - `vault/01_projects/` と `vault/03_companies/` のエントリ (分類用、空でも動作はする)
  - **ホストの LLM 推論** (議事録本文生成 / client/project 確信度判断 / owner 推論)
- **実行 (ホスト前提のため SKILL.md の手順に従う)**:

```bash
# 1. 未処理スキャン
python3 skills/meeting-summarizer/scripts/scan_inbox.py --pretty

# 2. 分類 (transcript 1 本ごと)
python3 skills/meeting-summarizer/scripts/classify_project.py --transcript <path> --pretty

# 3. 議事録生成 — ホストの LLM が templates/meeting.md を参照して書き出し

# 4. action items 抽出
python3 skills/meeting-summarizer/scripts/extract_action_items.py <meeting-md> --pretty

# 5. owner 推論 — ホストの LLM が議事録 + action items を読んで JSON 生成

# 6. タスク起票
python3 skills/meeting-summarizer/scripts/create_tasks_from_actions.py \
  --meeting <meeting-md> \
  --action-items <action-items.json> \
  --owner-inferences <owner.json>
```

- **推奨頻度**: 15 分 〜 1 時間ごと (新規 transcript 到着後)
- **冪等性**: frontmatter `tasks_extracted_at` で再処理を防止

詳細: [`skills/meeting-summarizer/SKILL.md`](../skills/meeting-summarizer/SKILL.md)

---

## person-enricher

**役割**: 議事録と元トランスクリプトを「人物視点」で再編成し、各人物の観察ログ・プロファイルを継続更新。

- **入力**: `vault/04_meetings/` の新形式議事録 (frontmatter `participants:` あり) + `00_inbox/.../processed/`
- **出力**:
  - `vault/02_people/<人物>/<人物>.md` (ホームノート: 基本情報 + プロファイル + 参加履歴)
  - `vault/02_people/<人物>/observations.md` (時系列観察ログ、append)
- **前提**:
  - `vault/02_people/<人物>/<人物>.md` が既に存在 (新規人物は skip、vault-resolver に委譲)
  - **ホストの LLM 推論** (観察抽出 / プロファイル合成)
- **実行 (SKILL.md の手順に従う)**:

```bash
# 1. 未処理議事録スキャン
python3 skills/person-enricher/scripts/scan_meetings_to_process.py --pretty

# 2. 各議事録 × 各参加者で観察を抽出 (LLM 推論はホスト)
# 3. 観察ログ追記 + ホームノート更新
python3 skills/person-enricher/scripts/update_person_note.py \
  --person "<姓名>" --meeting-date <date> --meeting-title "<title>" \
  --meeting-link "[[<filename>]]" --observation-json '<json>'

# 4. プロファイル再生成判定 (観察3件 or 7日経過)
python3 skills/person-enricher/scripts/update_state.py --action list-pending-synthesis

# 5. プロファイル合成 (LLM はホスト) → 書き込み
python3 skills/person-enricher/scripts/synthesize_profile.py \
  --person "<姓名>" --observation-count <N> --profile-content -
```

- **推奨頻度**: 1 日 1 回 (meeting-summarizer の後)
- **state**: `vault/ops/person-enricher/state.json` (last_processed_meeting_date 等)

詳細: [`skills/person-enricher/SKILL.md`](../skills/person-enricher/SKILL.md)

---

## vault-resolver

**役割**: vault 全体に散在する未解決 wikilink (02_people / 01_projects に存在しない人物・案件) を検出し、候補と一緒に通知。

- **入力**: vault 全体の `.md` ファイル
- **出力**: 通知 sink (vault は変更しない)
- **前提**: 任意でホストの LLM 補正 (信頼度補正 / concept 再分類)
- **実行**:

```bash
# 1. 未解決リンクのスキャン
python3 skills/vault-resolver/scripts/scan_unresolved.py

# 2. 候補推測
python3 skills/vault-resolver/scripts/suggest_candidates.py --link "<link>" --kind person --top 3

# 3. queue 更新
echo '<items_json>' | python3 skills/vault-resolver/scripts/update_queue.py \
  --action add-pending --items-json -

# 4. 通知 (ホストが最終応答を出力、または直接 notify.py を叩く)
```

- **推奨頻度**: 1 日 1 回
- **通知ポリシー**: 新規 pending は毎回、既存 pending は月曜のみリマインダ
- **state**: `vault/ops/resolver/queue.json` (pending / resolved / dismissed)

詳細: [`skills/vault-resolver/SKILL.md`](../skills/vault-resolver/SKILL.md)

---

## vault-sync

**役割**: `vault/` を Git remote 経由で複数マシン間で同期。ID 衝突を自動修復。

- **入力**: `vault/` (git working tree)
- **出力**: `git pull` → ID 衝突修復 → `git commit & push`、通知
- **前提**: `vault/` が git repo、`git push` が非対話で通る
- **実行**:

```bash
bash skills/vault-sync/scripts/sync.sh
```

- **推奨頻度**: 10 分ごと (cross-machine race を避けるため)
- **通知**: `notify.py` 経由で `NOTIFICATION_SINK` に従う
- **環境変数**: `VAULT_PATH`, `VAULT_SYNC_LOG`, `GIT_BIN`

詳細: [`skills/vault-sync/SKILL.md`](../skills/vault-sync/SKILL.md)

---

## 通知 sink

`skills/_common/notify.py` で抽象化。直接 webhook を叩いているのは現状 vault-sync のみ。
他の skill は stdout に出力し、ホストが Discord/Slack へルーティングする想定。

| 環境変数 | 役割 |
|---|---|
| `NOTIFICATION_SINK` | `discord` / `slack` / `stdout` / `file` |
| `DISCORD_WEBHOOK_URL` | sink=discord 時に必要 |
| `SLACK_WEBHOOK_URL` | sink=slack 時に必要 |
| `NOTIFICATION_FILE_PATH` | sink=file 時 (デフォルト `./logs/notifications.log`) |
