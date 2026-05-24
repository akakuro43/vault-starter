# Inbox ルーティングルール

`00_inbox/` に着地した自動取込ファイルを、適切な振り分け先に流すためのルール。
このリポジトリの skill 群（mtg-importer / meeting-summarizer / person-enricher 等）が参照する。

## Meet 文字起こし

- 取込元: Google Drive `MTG_Transcripts/` (mtg-importer)
- 着地先: `vault/00_inbox/meeting_transcripts/<date>_<title>.md`
- 議事録化先: `vault/04_meetings/<date>_<title>.md` (meeting-summarizer)
- 副作用: `02_people/<参加者>/observations.md` に観察追加 (person-enricher)、
  `05_tasks/T####-*.md` にタスク起票 (meeting-summarizer)

## Gmail（任意・本リポジトリには未同梱）

- 領収書 → `00_inbox/` に経費タグ付きで保存
- クライアントメール → `01_projects/<slug>/sources/` に追記

## Slack（任意・本リポジトリには未同梱）

- チャンネル名から案件を判定して `00_inbox/` 経由でプロジェクトに振り分け

## Calendar（任意・本リポジトリには未同梱）

- 予定をタスクとして `05_tasks/` に登録

---

本リポジトリで動くのは **Meet 文字起こし** のルートのみ。
Gmail / Slack / Calendar 連携は雛形なし。必要なら自作してください。
