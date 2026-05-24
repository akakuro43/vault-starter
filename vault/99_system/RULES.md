# Vault 読み込みルール（AI向け Traversal Contract）

## 読み込み順序

1. まず `vault/CLAUDE.md` を読む（→ `vault/AGENTS.md` を参照）
2. 必要なら `99_system/index.md`（プロジェクト一覧）を読む
3. 質問に関連するファイルを読む（最大3ファイル）

## ディレクトリの役割

```
00_inbox/        API自動取込の着地点（読むのはルーティング処理のみ）
01_projects/     仕事案件（プロジェクト別ディレクトリ）
02_people/       人物情報（per-person ディレクトリ + observations.md）
03_companies/    会社・組織エンティティ
04_meetings/     議事録（inboxから振り分け後）
05_tasks/        タスク管理
06_knowledge/    プロジェクト横断のナレッジ
  insights/      アトミックインサイト
  references/    外部から仕入れた情報のストック
  frameworks/    複数案件で使う方法論
  explorations/  探究テーマ（問いベース）
99_system/       Vault自体のルール・テンプレート（このディレクトリ）
```

## 質問タイプ別の入口

| 質問のパターン | 最初に読むファイル |
|---|---|
| 「ディレクトリ構造・方法論」 | `vault/AGENTS.md` |
| 「テンプレート・スキーマ」 | `99_system/templates/<entity_type>.md` |
| 「ある人物との直近のやりとり」 | `02_people/<人物>/<人物>.md` → 関連 meeting |
| 「あるプロジェクトの状況」 | `01_projects/<slug>/<slug>.md` |
| 「ある会社との関係」 | `03_companies/<slug>.md` |

## 禁止事項

- 推測で存在しないファイルを参照しない
- 3hop以上の参照チェーン（A→B→C→D）は踏まない
- 情報がなければ「Vaultに該当情報なし」と返す（推測で埋めない）
- `00_inbox/` のファイルは直接参照しない（ルーティング後のファイルを読む）
