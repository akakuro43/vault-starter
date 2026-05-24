---
_schema:
  entity_type: insight-note
  applies_to: "06_knowledge/insights/*.md"
  required:
    - description
  optional:
    - type
    - status
    - created
    - modified
  enums:
    type:
      - insight
      - pattern
      - decision
      - question
      - tension
      - methodology
      - anti-pattern
    status:
      - preliminary
      - open
      - active
      - archived
  constraints:
    description:
      max_length: 200
      format: "タイトル以外の情報を1文で追加（句点なし）"
    topics:
      format: "Wikiリンクの配列"

# テンプレートフィールド
description: ""
type: insight
created: YYYY-MM-DD
topics: []
---

# {命題として機能するタイトル — 主張として読める文または句}

{本文 — このインサイトの推論・証拠・文脈}

---

Relevant Notes:
- [[関連ノート]] — 関係性の説明（「〜を拡張する」「〜の証拠として」など）

Topics:
- [[関連トピックマップ]]
