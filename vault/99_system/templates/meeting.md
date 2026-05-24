---
_schema:
  entity_type: meeting
  applies_to: "04_meetings/*.md"
  required:
    - description
    - date
  optional:
    - client
    - project
    - participants
    - tags
    - status
  enums:
    status:
      - done
      - needs-processing
      - archived
  constraints:
    description:
      max_length: 200
      format: "この会議の主要決定・目的の1文サマリー（句点なし）"

# テンプレートフィールド
description: ""
type: meeting
date: YYYY-MM-DD
client: ""
project: ""
participants: []
tags: []
status: needs-processing
---

# {会議タイトル}

## アジェンダ

## 議事

## 決定事項

## TODO

- [ ]

## インサイト候補

（処理時に 06_knowledge/insights/ に昇格させる候補）

---

Topics:
- [[04_meetings/index]]
