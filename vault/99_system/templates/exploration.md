---
_schema:
  entity_type: exploration
  applies_to: "06_knowledge/explorations/*/_index.md"
  required:
    - description
    - question
    - status
  optional:
    - started
    - tags
  enums:
    status:
      - active
      - paused
      - completed
      - archived
  constraints:
    description:
      max_length: 200
      format: "この探究が答えようとしている問いと現在の状態（句点なし）"
    question:
      format: "問いの形式で記述（「〜か？」「〜とはどういうことか」）"

# テンプレートフィールド
description: ""
type: exploration
question: ""
status: active
started: YYYY-MM-DD
tags: []
---

# {探究テーマ名}

## 問い

{中心的な問いを記述}

## なぜこれを探究するか

## 現在地（フェーズ・状態）

## 関連ファイル

## 次のアクション

- [ ] 

## 参照・ソース

---

Topics:
- [[06_knowledge/explorations/index]]
