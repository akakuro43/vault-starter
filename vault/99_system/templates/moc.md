---
_schema:
  entity_type: moc
  applies_to: "**/*index*.md, **/*map*.md"
  required:
    - description
  optional:
    - type
  constraints:
    description:
      max_length: 200
      format: "このMOCがカバーするトピックエリアの1文サマリー（句点なし）"

# テンプレートフィールド
description: ""
type: moc
---

# {MOCタイトル}

## Overview

## {カテゴリ1}

- [[ノートA]] — 文脈説明
- [[ノートB]] — 文脈説明

## {カテゴリ2}

- [[ノートC]] — 文脈説明

---

（MOCが〜35ノートを超えたら子MOCを作成して分割）
