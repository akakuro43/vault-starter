---
_schema:
  entity_type: project
  applies_to: "01_projects/*/*.md"
  directory_convention: |
    各プロジェクトは自身のディレクトリを持ち、ホームノートはディレクトリと同名の .md ファイルとして格納する。
    例: 01_projects/my-project/my-project.md

    サブディレクトリ（必要時に作成、スパース運用）:
      - sources/      他者由来の生データ・先方資料・インタビュー逐語
      - work/         自分が書いてる流動物（同種2件以上で発生したらディレクトリ化）
      - deliverables/ 確定した最終成果物（クライアントに渡るもの）

    work/ 内ファイルの命名 prefix:
      - note-*         気づき・対話分析・議事録から拾った観察（汎化前）
      - analysis-*     構造化分析（競合分析、状況分析、評価設計）
      - design-*       設計ドキュメント（カリキュラム、要件、仕様、プラン）
      - log-YYYY-MM-DD 進捗・時系列ログ

    検討中・下書きは frontmatter `status: draft` で管理（ファイル名 prefix で表現しない）。
    確定したら deliverables/ に移管。

    詳細は 01_projects/index.md または vault/AGENTS.md を参照。
  required:
    - description
    - name
    - status
  optional:
    - client
    - operator
    - lead
    - members
    - started
    - ended
    - deadline
    - tags
    - last_activity
    - keywords
    - aliases
    - excluded_keywords
    - participant_signatures
    - is_recurring
    - cadence
    - notion_page_id
    - notion_url
  enums:
    status:
      - active
      - paused
      - completed
      - archived
    cadence:
      - daily
      - weekly
      - biweekly
      - monthly
      - irregular
  constraints:
    description:
      max_length: 200
      format: "目的・クライアント・現在の状態を1文で要約（句点なし）"

# テンプレートフィールド
description: ""
type: project
name: ""
client: ""
operator: ""
status: active
lead: ""
members: []
started: ""
ended: ""
deadline: ""
tags: []
last_activity: ""
# --- 議事録分類用メタデータ（meeting-summarizer が使用） ---
keywords: []                      # タイトル・本文で検索するキーワード
aliases: []                       # プロジェクトの呼称揺れ
excluded_keywords: []             # これが含まれたら別PJ（negative signal）
participant_signatures:           # 参加者パターン
  required_any: []                # このうち1人でも居れば確度↑
  excluded: []                    # 居たら確度↓
is_recurring: false
cadence: ""                       # weekly | biweekly | monthly 等
notion_page_id: ""                # Notion連携用
notion_url: ""
---

# {プロジェクト名}

## 概要

<このプロジェクトが何をやるものか、3〜5文で>

## 目的・ゴール

<受注時の目的・成功条件、または主要テーマ>

## メンバー

- リード: [[]]
- 自社（{operator}）: [[]]
- クライアント側: [[]] （詳細は [[<クライアント会社>]] の ## メンバー セクション参照）

## 現在のフェーズ

<現在の進行段階を1〜3文で>

## ディレクトリ構成

- [`sources/`](sources/) — 先方提供資料・インタビュー逐語・生データ
- [`work/`](work/) — 設計・分析・気づき・進捗ログ
- [`deliverables/`](deliverables/) — 確定した成果物

## 主要ドキュメント

<重要なファイルへの pin link。全件列挙ではなく代表のみ>

- [[work/design-XXX]] — XXX設計
- [[work/analysis-YYY]] — YYY分析

## 議事録

```dataview
TABLE WITHOUT ID file.link AS "議事録", date AS "日付"
FROM "04_meetings"
WHERE contains(string(project), this.file.name)
SORT date DESC
LIMIT 20
```

## ネクストアクション

- [ ] 

## 関連

- [[<関連プロジェクト>]]
- [[<会社>]]

---

Topics:
- [[01_projects/index]]
