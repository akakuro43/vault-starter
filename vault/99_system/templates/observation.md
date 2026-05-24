---
_schema:
  entity_type: observation
  applies_to: "ops/observations/*.md"
  required:
    - description
    - category
    - observed
    - status
  optional:
    - promoted_to
  enums:
    category:
      - friction
      - surprise
      - process-gap
      - methodology
      - quality
    status:
      - pending
      - promoted
      - implemented
      - archived
  constraints:
    description:
      max_length: 200
      format: "観察内容の1文サマリー（句点なし）"

# テンプレートフィールド
description: ""
category: friction
observed: YYYY-MM-DD
status: pending
---

# {観察内容を命題として表現}

## 何が起きたか

## どう対応すべきか

## 対応状況

---

Topics:
- [[ops/methodology/methodology]]
