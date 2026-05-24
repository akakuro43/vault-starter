# 会議トランスクリプトを Obsidian に自動で振り分けるシステム「vault-starter」を導入する

> note 用ドラフト。手順を細かめに書いています。コードブロック・スクリーンショット位置の目安 (📸) を入れているので、実際にスクショ撮影しながら投稿してください。

---

## はじめに

Google Meet の会議が増えると、文字起こし (トランスクリプト) は溜まる一方なのに、

- **議事録**として整理する手間
- 誰がどんな発言をしたかという **人物理解**
- 会議で出た **TODO の取りこぼし**

がボトルネックになります。

vault-starter は、これらを Obsidian Vault に自動で振り分ける Python スクリプト群です。Google Drive にトランスクリプトが届くと、

1. **議事録** (`vault/04_meetings/`)
2. **人物プロファイル + 観察ログ** (`vault/02_people/`)
3. **タスク** (`vault/05_tasks/`)
4. **未解決 wikilink の通知** (Discord / Slack 等)

に自動で配置されます。

> 設計上の特徴: skill スクリプト自体は LLM を直接呼びません。議事録の要約・人物プロファイルの合成といった「賢い処理」は、Claude Code や Hermes といったホストエージェントが担当します。つまり配布物に Anthropic API key を含めずに済むので、入手者は自分の AI 環境に組み込んで使えます。

GitHub: **https://github.com/akakuro43/vault-starter**

---

## このシステムでできること (概観)

```
[Google Drive: MTG_Transcripts/]
        │
        │  mtg-importer (Python)
        ▼
[vault/00_inbox/meeting_transcripts/*.md]   ← 取り込み完了
        │
        │  meeting-summarizer (Claude Code 等)
        ▼
[vault/04_meetings/<日付>_<タイトル>.md]    ← 構造化された議事録
[vault/05_tasks/T####-*.md]                  ← action items から起票されたタスク
        │
        │  person-enricher (Claude Code 等)
        ▼
[vault/02_people/<姓名>/observations.md]    ← 会議ごとの観察ログ
[vault/02_people/<姓名>/<姓名>.md]           ← 10 セクションのプロファイル
        │
        │  vault-resolver
        ▼
[Discord/Slack 通知]   未登録の人物・案件を「これ作りますか?」と尋ねる
```

📸 (この図は note の埋め込み画像にしても良いです)

---

## 必要なもの

| 必須 | 用途 |
|---|---|
| **macOS または Linux** | Windows は WSL2 上で同様に動くはず (未検証) |
| **Python 3.11+** | スクリプト実行 |
| **[uv](https://docs.astral.sh/uv/)** | Python 環境管理ツール |
| **Obsidian** | Vault を開いて閲覧・編集する |
| **Google アカウント** | Google Meet のトランスクリプトが Drive に保存される前提 |
| **Google Cloud Console アカウント** | Drive API の OAuth credentials を作るため (無料枠で十分) |
| **GitHub アカウント** | clone するため |

| 任意 | 用途 |
|---|---|
| **Claude Code または Hermes** | 議事録要約・人物プロファイル合成の AI 処理を担う |
| **Discord / Slack の Webhook URL** | 通知を受け取りたい場合 |
| **Git remote (GitHub の private repo 等)** | 複数端末で Vault を同期したい場合 |

---

## Step 1 — uv をインストール

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

インストール後、ターミナルを再起動 (または `source ~/.zshrc` 等) してから:

```bash
uv --version
# → uv 0.x.x のように表示されれば OK
```

📸 ターミナル

---

## Step 2 — vault-starter を clone

```bash
# 好きな場所にどうぞ。私は ~/develop/ 配下を使っています
git clone https://github.com/akakuro43/vault-starter.git ~/develop/my-vault
cd ~/develop/my-vault
```

📸 ディレクトリツリー

---

## Step 3 — bootstrap で環境構築

```bash
./bootstrap.sh
```

このスクリプトは次を自動でやります:

1. `.env` を `.env.example` からコピー
2. Python 仮想環境 `.venv/` を作成
3. 依存パッケージをインストール (Google API クライアント / html2text / pyyaml)
4. `logs/` / `credentials/` / `vault/00_inbox/meeting_transcripts/` を作成

完了後、画面に次のような Next Steps が表示されます:

```
== bootstrap complete ==

Next steps:
  1. .env を編集
  2. Google Drive OAuth credentials を配置
  3. 認証テスト
  4. 初回トランスクリプト取り込み
```

📸 bootstrap 完了画面

---

## Step 4 — Google Drive の OAuth credentials を作る

これが少し面倒ですが、一度作れば使い回せます。

### 4-1. Google Cloud Console でプロジェクト作成

1. https://console.cloud.google.com/ にアクセス
2. 上部のプロジェクト選択 → **新しいプロジェクト** → 名前は何でも OK (例: `vault-starter`)

📸 プロジェクト作成画面

### 4-2. Google Drive API を有効化

1. 左メニュー → **API とサービス** → **ライブラリ**
2. 「Google Drive API」を検索 → **有効にする**

📸 API 有効化画面

### 4-3. OAuth 同意画面を設定

1. 左メニュー → **API とサービス** → **OAuth 同意画面**
2. **外部** を選んで作成
3. 必要項目 (アプリ名 / サポートメール / デベロッパーメール) を入力
4. **スコープ** は追加不要 (次のステップで credentials 側で指定)
5. **テストユーザー** に自分のメールを追加 (これをやらないと認証時に弾かれる)

📸 OAuth 同意画面の各タブ

### 4-4. OAuth クライアント ID を作成

1. 左メニュー → **API とサービス** → **認証情報**
2. **認証情報を作成** → **OAuth クライアント ID**
3. アプリケーションの種類: **デスクトップアプリ**
4. 名前: 何でも (例: `vault-starter-desktop`)
5. 作成後、**JSON をダウンロード**

📸 ダウンロードボタン

### 4-5. JSON を配置

ダウンロードした JSON を以下の場所に **`google-drive.json`** という名前で置きます:

```bash
mv ~/Downloads/client_secret_XXXXX.json ~/develop/my-vault/credentials/google-drive.json
```

---

## Step 5 — .env を編集

```bash
# お好みのエディタで開く
code .env       # VS Code
vim .env        # vim
open -t .env    # macOS の TextEdit
```

最低限、以下を埋めてください:

```bash
# Drive のトランスクリプトフォルダ ID
# → Drive 上でフォルダを開いた時の URL の末尾
#   例: https://drive.google.com/drive/folders/1abc...xyz の場合は 1abc...xyz
GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID=1abc...xyz

# 自分の組織情報 (カンマ区切り)
YOUR_EMAIL_DOMAINS=example.com
YOUR_ORGANIZATIONS=MyCompany Inc

# 通知の出力先 — まず動作確認したいなら stdout のままで OK
NOTIFICATION_SINK=stdout
# Discord に送りたい場合:
# NOTIFICATION_SINK=discord
# DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

📸 編集後の .env

> **ヒント**: トランスクリプトフォルダ ID が分からない場合、フォルダ名検索でも動きます。`GOOGLE_DRIVE_TRANSCRIPT_FOLDER=MTG_Transcripts` (デフォルト値) のままでも、その名前のフォルダが Drive 上で 1 つだけなら自動で見つけます。

---

## Step 6 — 認証テスト

```bash
source .venv/bin/activate
python3 skills/mtg-importer/scripts/auth_test.py
```

初回はブラウザが開いて Google ログインを求められます。**Step 4-3 で追加したテストユーザーのメール**でログインしてください。

「Google にデータへのアクセスを許可しますか?」のような画面が出るので **続行 → 許可**。

成功すると:

```
OK 認証成功
OK MTG_Transcripts フォルダ発見: id=1abc...
```

`credentials/token.json` が生成されます (今後の認証はこれが使い回されます)。

📸 認証成功画面

---

## Step 7 — 初回トランスクリプト取り込み

```bash
python3 skills/mtg-importer/scripts/fetch_transcripts.py
```

**初回は自動で seed モード**になります。これは「既存ファイルを取り込み済みとして記録だけする」モードで、過去のトランスクリプトを全部 Markdown 化はしません。**次回以降の実行で新規ファイルだけ取り込む**ためです。

```
モード: シード（初回実行） — 既存ファイルを記録のみ。本文は取り込まない
対象ファイル数: 45
  SEED TRANSCRIPT_25.10.01_xxxx
  SEED TRANSCRIPT_25.10.02_xxxx
  ...
完了 — シード記録: 45件 / スキップ: 0件
```

📸 seed モード出力

次に新しい会議があってから再度実行すると:

```bash
python3 skills/mtg-importer/scripts/fetch_transcripts.py
```

```
モード: 通常運用（新規ファイルのみ取り込み）
対象ファイル数: 46
  OK 2026-05-25_企画会議.md
完了 — 新規: 1件 / スキップ: 45件 / エラー: 0件
```

`vault/00_inbox/meeting_transcripts/` に Markdown ファイルが落ちていれば成功です。

---

## Step 8 — Obsidian で Vault を開く

Obsidian を起動 → **別の Vault を開く** → `~/develop/my-vault/vault/` を選択。

📸 Obsidian の Vault 選択画面

開くと、次のような構造が見えます:

```
00_inbox/         ← 取り込んだトランスクリプト
01_projects/      ← 仕事案件 (自分で追加)
02_people/        ← 人物 (自分で追加 → AI が育てる)
03_companies/     ← 会社 (自分で追加)
04_meetings/      ← 議事録 (AI が生成)
05_tasks/         ← タスク (AI が起票)
06_knowledge/     ← 横断ナレッジ
99_system/        ← テンプレ・ルール
AGENTS.md         ← 方法論マニュアル
CLAUDE.md         ← Claude Code 用エントリ
```

---

## 動作確認のチェックポイント

- [ ] `bootstrap.sh` がエラーなく完了する
- [ ] `python3 skills/mtg-importer/scripts/auth_test.py` で「OK 認証成功」が出る
- [ ] `python3 skills/mtg-importer/scripts/fetch_transcripts.py` 実行後、`vault/00_inbox/meeting_transcripts/` に `.md` ファイルが落ちている (seed モード後の通常モードで)
- [ ] Obsidian で Vault を開いて、ファイルが見える
- [ ] `vault/99_system/templates/` にテンプレが 8 個ある

ここまで動けば、トランスクリプト取り込みのパイプラインは完成です。

---

## 発展編 — Claude Code や Hermes と組み合わせる

ここまでは「取り込み」だけ。トランスクリプトを **議事録に要約する** には LLM 推論が必要で、これは Claude Code か Hermes 等のホストエージェントから呼ぶ設計になっています。

### Claude Code で動かす場合

`vault/` を Claude Code のワークスペースとして開き、

```
/meeting-summarizer
```

のような呼び方をすると、SKILL.md の手順 (= 議事録を Markdown 化して `vault/04_meetings/` に書き出し、action items をタスクとして `vault/05_tasks/` に起票) を Claude が実行してくれます。

詳細は `skills/meeting-summarizer/SKILL.md` と `docs/skills-catalog.md` を参照。

### Hermes で動かす場合

```toml
# ~/.hermes/config.toml
[external_dirs]
paths = ["/path/to/my-vault/skills"]
```

を追記して Hermes に skill を発見させる。cron 登録で自動実行可能。

### 素の cron で完結させたい場合

`mtg-importer` と `vault-sync` は素の cron でも完結します:

```cron
5  * * * * /bin/bash /path/to/my-vault/skills/mtg-importer/scripts/pipeline.sh
*/10 * * * * /bin/bash /path/to/my-vault/skills/vault-sync/scripts/sync.sh
```

`meeting-summarizer` と `person-enricher` は LLM が必要なので、間にホストを挟む必要があります。

---

## よくあるつまずき

### `uv: command not found`

uv のインストール後にターミナルを再起動していない可能性。

```bash
exec $SHELL  # シェルを再起動
```

### `credentials file not found`

`credentials/google-drive.json` が無い、または名前が違う。Step 4-5 を確認。

### `MTG_Transcripts フォルダが見つかりません`

Drive 上のフォルダ名が `MTG_Transcripts` ではない場合、`.env` の `GOOGLE_DRIVE_TRANSCRIPT_FOLDER` を実フォルダ名に合わせるか、`GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID` でフォルダ ID を直接指定。

### 認証時に「このアプリは Google で確認されていません」と出る

OAuth 同意画面でテストユーザーに追加していない / アプリが本番公開モードになっている可能性。

- テストユーザーに自分のメールを追加 (Step 4-3)
- もしくは「**詳細**」→「(プロジェクト名) に移動 (安全ではないページ)」で進む

### Obsidian で wikilink が壊れて見える

vault フォルダの中で Obsidian を開いていない可能性。`~/develop/my-vault/` ではなく、その下の `~/develop/my-vault/vault/` を選択してください。

### `bootstrap.sh` で「uv が見つかりません」と言われる

PATH に uv が入っていない。インストール直後はシェル再起動が必要。Step 1 を確認。

---

## カスタマイズアイデア

| やりたいこと | 触る場所 |
|---|---|
| 通知先を Discord に切り替え | `.env` の `NOTIFICATION_SINK=discord` + `DISCORD_WEBHOOK_URL` |
| Slack に切り替え | `.env` の `NOTIFICATION_SINK=slack` + `SLACK_WEBHOOK_URL` |
| ファイル出力でデバッグ | `.env` の `NOTIFICATION_SINK=file` |
| Drive のフォルダ名を変える | `.env` の `GOOGLE_DRIVE_TRANSCRIPT_FOLDER=<名前>` |
| Vault の場所を変える | `.env` の `VAULT_PATH=/path/to/vault` |
| 議事録テンプレを変更 | `vault/99_system/templates/meeting.md` を編集 |
| 人物プロファイルの構成変更 | `skills/person-enricher/SKILL.md` の「プロファイル 10 セクション」を編集 |
| 新しい skill を追加 | `skills/<name>/SKILL.md` + `scripts/` を追加 |

---

## まとめ

vault-starter を入れることで、Google Meet のトランスクリプトが Obsidian に自動で構造化されて溜まる環境を作れます。

- **mtg-importer** — Drive 取り込み (素の cron で OK)
- **meeting-summarizer** — 議事録化 + タスク化 (LLM ホスト必要)
- **person-enricher** — 人物プロファイル合成 (LLM ホスト必要)
- **vault-resolver** — 未解決リンク検出 (LLM 補正は任意)
- **vault-sync** — 複数端末同期 (Git remote 必要)

LLM 推論を含む部分は Claude Code か Hermes との組み合わせを推奨。

GitHub: **https://github.com/akakuro43/vault-starter**

質問・要望があれば Issue でどうぞ。
