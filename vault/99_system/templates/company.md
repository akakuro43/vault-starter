---
_schema:
  entity_type: company
  applies_to: "03_companies/*.md"
  required:
    - description
    - name
  optional:
    - aliases
    - industry
    - relationship
    - category
    - via
    - status
    - primary_contact
    - contacts
    - projects
    - meeting_count
    - last_meeting
    - notes
  enums:
    relationship:
      - client
      - partner
      - vendor
      - prospect
      - other
    category:
      - client
      - affiliate
      - employer
      - partner
      - target
    status:
      - active
      - paused
      - archived
  constraints:
    description:
      max_length: 200
      format: "この会社との関係性・業種の1文サマリー（句点なし）"

# テンプレートフィールド
description: ""
type: company
name: ""
aliases: []
industry: ""
relationship: client
category: client
via: ""
status: active
primary_contact: ""
contacts: []
projects: []
meeting_count: 0
last_meeting: ""
---

# {会社名}

## 概要

## 関係性

## 案件・プロジェクト

## メモ

---

Topics:
- [[03_companies/index]]
