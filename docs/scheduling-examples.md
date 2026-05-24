# Scheduling Examples

各 skill は CLI として呼べるので、好みのスケジューラから定期実行してください。
本リポジトリはスケジューラ自体を同梱しません。

## 推奨頻度

| Skill | 推奨頻度 | 備考 |
|---|---|---|
| mtg-importer | 毎時 | Drive にトランスクリプトが到着する頻度に合わせる |
| meeting-summarizer | 15 分 〜 1 時間 | mtg-importer の後 |
| person-enricher | 1 日 1 回 (深夜) | meeting-summarizer の後 |
| vault-resolver | 1 日 1 回 (深夜) | person-enricher の後 |
| vault-sync | 10 分ごと | cross-machine race 避け |

依存関係: `mtg-importer → meeting-summarizer → person-enricher → vault-resolver`。
vault-sync は独立 (vault 全体に常時走らせて OK)。

---

## 例 1: crontab (macOS / Linux)

```cron
# 毎時 5 分: Drive から取り込み
5  * * * * /bin/bash /path/to/vault-starter/skills/mtg-importer/scripts/pipeline.sh

# 毎時 10 分: 議事録化 (ホストの LLM 推論が必要なので注意)
# 直接 cron からは呼べない。ホストエージェントの cron に組み込む必要あり

# 毎日 03:00: vault-resolver
0  3 * * * cd /path/to/vault-starter && /path/to/vault-starter/.venv/bin/python3 skills/vault-resolver/scripts/scan_unresolved.py

# 毎日 04:00: person-enricher (これもホストの LLM が必要、ホスト側で起動)

# 10 分ごと: vault-sync
*/10 * * * * /bin/bash /path/to/vault-starter/skills/vault-sync/scripts/sync.sh
```

**重要**: `meeting-summarizer` と `person-enricher` は LLM 推論を必要とするため、素の cron から呼んでも完結しません。下記の Hermes / Claude Code Routines を使うか、自前で「LLM ホスト経由で呼ぶスケジューラ」を組む必要があります。

---

## 例 2: launchd (macOS native)

`~/Library/LaunchAgents/com.example.mtg-importer.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.example.mtg-importer</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/path/to/vault-starter/skills/mtg-importer/scripts/pipeline.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Minute</key>
    <integer>5</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/path/to/vault-starter/logs/launchd-mtg-importer.out</string>
  <key>StandardErrorPath</key>
  <string>/path/to/vault-starter/logs/launchd-mtg-importer.err</string>
</dict>
</plist>
```

ロード: `launchctl load ~/Library/LaunchAgents/com.example.mtg-importer.plist`

---

## 例 3: Hermes (推奨)

[Hermes](https://github.com/anthropics/hermes) は Claude Agent SDK ベースのスケジューラで、skill を自動発見します。

```bash
# 1. skills/ ディレクトリを Hermes に登録 (~/.hermes/config.toml に追記)
[external_dirs]
paths = ["/path/to/vault-starter/skills"]

# 2. cron 登録 (Hermes 内で)
hermes cron add --skill mtg-importer --schedule "5 * * * *"
hermes cron add --skill meeting-summarizer --schedule "*/15 * * * *"
hermes cron add --skill person-enricher --schedule "0 4 * * *"
hermes cron add --skill vault-resolver --schedule "0 3 * * *"
```

Hermes が SKILL.md の `description` を読んで自動でホストエージェントから呼ぶ。LLM 推論も Hermes 側で完結。

---

## 例 4: Claude Code Routines

Claude Code の Routines 機能 ([参考](https://docs.claude.com/ja/docs/claude-code/routines)) を使う場合:

```bash
# routine を作成
claude routine create --name mtg-importer --skill /skills/mtg-importer --schedule "5 * * * *"
```

skill の SKILL.md がそのまま Routines 用 prompt として動作。LLM 推論を含む meeting-summarizer / person-enricher もこの方式で完結する。

---

## 例 5: 手動実行 (動作確認用)

```bash
# venv 有効化
source .venv/bin/activate

# Drive 取り込み
python3 skills/mtg-importer/scripts/fetch_transcripts.py

# 未解決 wikilink を確認
python3 skills/vault-resolver/scripts/scan_unresolved.py | jq .

# vault sync
bash skills/vault-sync/scripts/sync.sh
```

---

## LLM ホストを伴う skill の扱い

`meeting-summarizer` / `person-enricher` / `vault-resolver` (LLM 補正部分) は、SKILL.md に書かれた手順をホストエージェント (Claude Code / Hermes 等) が実行する前提です。

これらを cron / launchd から呼ぶ場合、間に「LLM 推論を行うホスト」を挟む必要があります:

- Hermes / Claude Code Routines を使う → そのままスケジュール可能
- 素の cron で組む → 各 skill を呼ぶラッパースクリプトを自作する必要あり (SKILL.md の手順を Python で書き起こすか、Anthropic API を直接叩く処理を追加)
