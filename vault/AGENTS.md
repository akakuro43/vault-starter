# AGENTS.md — Vault 方法論マニュアル

> このファイルは Claude Code / Codex / Hermes など全 AI エージェント共通の方法論マニュアルです。
> セッション冒頭に読んでください。

このマニュアルは **vault-starter** リポジトリで生成される Vault の最小運用ガイドです。
ナレッジ管理方法論全体（Atomic Notes / Processing Pipeline / self/ / ops/ 等）には踏み込んでいません。
Vault を自分流に拡張する場合は、このマニュアルを基点にカスタマイズしてください。

---

## Philosophy

会議トランスクリプトを起点に「議事録 / 人物プロファイル / タスク」を継続的に蓄積し、
過去の文脈を AI が引き出せる状態に保つ。書き手は skill が担い、人間は判断と確認に集中する。

---

## Vault 構造

```
vault/
├── AGENTS.md                   ← このファイル
├── 00_inbox/                   ← 自動取込の着地点
│   └── meeting_transcripts/    ← Google Meet トランスクリプト (mtg-importer が配置)
├── 01_projects/                ← 仕事案件（プロジェクト別ディレクトリ）
├── 02_people/                  ← 人物情報（per-person ディレクトリ）
├── 03_companies/               ← 会社・組織エンティティ
├── 04_meetings/                ← 議事録（meeting-summarizer が生成）
├── 05_tasks/                   ← タスク管理（meeting-summarizer が起票）
├── 06_knowledge/               ← プロジェクト横断ナレッジ
│   ├── insights/
│   ├── frameworks/
│   ├── references/
│   └── explorations/
└── 99_system/                  ← Vault のルール・テンプレート
    ├── RULES.md
    ├── routing.md
    └── templates/
```

---

## どこに何を書くか

| コンテンツタイプ | 保存先 |
|----------------|--------|
| 会議トランスクリプト（自動取込） | `00_inbox/meeting_transcripts/` |
| 議事録（構造化済み） | `04_meetings/<date>_<title>.md` |
| 人物情報 | `02_people/<姓名>/<姓名>.md` + `observations.md` |
| 会社情報 | `03_companies/<slug>.md` |
| プロジェクト情報 | `01_projects/<slug>/<slug>.md` |
| タスク | `05_tasks/T####-<slug>.md` |
| 横断ナレッジ | `06_knowledge/insights/` |

迷ったら「これは永続的な知識か、案件依存か、誰かに紐づくか」で判断する。

---

## プロジェクトのディレクトリ構造

各プロジェクトは自身のディレクトリを持ち、ホームノートはディレクトリと同名の `.md`。

```
01_projects/
├── my-project/
│   ├── my-project.md          ← ホームノート（エントリーポイント）
│   ├── sources/                ← 他者由来の生データ・先方資料
│   ├── work/                   ← 自分が書いてる流動物
│   │   ├── note-*.md           気づき・観察
│   │   ├── analysis-*.md       構造化分析
│   │   ├── design-*.md         設計ドキュメント
│   │   └── log-YYYY-MM-DD.md   進捗ログ
│   └── deliverables/           ← 確定した最終成果物
└── index.md                    ← プロジェクト一覧 MOC
```

- 新規プロジェクト作成時は必ずディレクトリを先に作る
- ホームノートは `<project-name>/<project-name>.md`（ディレクトリと同名）
- サブディレクトリは **必要なときだけ作る**（同種ファイルが2件以上発生してから）
- 検討中・下書きは frontmatter `status: draft` で管理

---

## 人物ノートのディレクトリ構造

各人物は自身のディレクトリを持ち、ホームノートと観察ログを分離する。

```
02_people/
├── 山田太郎/
│   ├── 山田太郎.md            ← ホームノート（基本情報 / プロファイル / 参加履歴）
│   └── observations.md         ← 観察ログ（時系列の生データ蓄積）
└── map.md                      ← 人物一覧 MOC
```

- **書き手は person-enricher skill が唯一**（人手では基本情報だけ追記）
- 新規人物は手動で `02_people/<姓名>/<姓名>.md` を作成。skill は自動作成しない
- ホームノートには **観察ログそのものを書かない**。観察エントリは `observations.md` 側に append
- プロファイル合成は `## プロファイル` セクションとしてホームノートに置く（観察ログを LLM 合成した結果）

### プロファイル 10 セクション

person-enricher が合成するプロファイルは以下のサブセクションで構成（詳細は person-enricher SKILL.md）:

役割と立場 / 強い関心領域 / 専門性・知見 / 動機・ドライバー / 懸念・課題視点 / 意思決定スタイル / コミュニケーションパターン / 関係性 / 直近の文脈 / 未確認・仮説

---

## Wiki リンク

`[[ノートタイトル]]` がグラフのエッジ。リンクは「関係の主張」。

- リンクは文章の一部として読める形に書く: `[[山田太郎]] と先週話した件で...`
- bare link より「〜なぜなら [[note]]」のように関係の理由を明示する
- 双方向（A が B にリンクしたら、B も A を知っているべき）

---

## トピックマップ（MOC）

注意管理のハブ。グラフを前進させる入口。

- MOC は整理ではなくナビゲーション
- コンテキスト句を添える: `[[X]] — Yの観点から重要`
- 〜35 ノートで分割

---

## スキーマ — frontmatter 規約

すべてのノートに YAML frontmatter。スキーマなしではノートはただのファイル。

### 議事録ノート

```yaml
---
description: 1文サマリー（句点なし、150字以内）
type: meeting
date: YYYY-MM-DD
client: "[[<company slug>]]" | "unclassified"
project: "[[<project slug>]]" | "unclassified"
participants: ["[[姓名]]", ...]
transcript: "[[<transcript filename>]]"
generated: YYYY-MM-DD
tags: []
---
```

### 人物ノート

```yaml
---
description: この人物の役割・関係性の1文サマリー
type: person
name: 姓名
org: 所属組織
role: 役割・肩書き
projects: []
meeting_count: 0
last_meeting: ""
related_projects: []
---
```

### 会社ノート

```yaml
---
description: この会社との関係性・業種の1文サマリー
type: company
name: 会社名
aliases: []           # 呼称揺れ（議事録分類で照合）
industry: 業種
relationship: client | partner | vendor | prospect | other
projects: []
---
```

### プロジェクトノート

```yaml
---
description: 目的・クライアント・現在の状態を1文で要約
type: project
name: ""
client: ""
operator: ""
status: active | paused | completed | archived
keywords: []          # 議事録分類で照合
aliases: []
participant_signatures:
  required_any: []
  excluded: []
---
```

詳細・enum 値は `99_system/templates/` のテンプレートを参照。

---

## テンプレート

`99_system/templates/` に保存されたテンプレートが**スキーマの唯一の真実の源**。
新しいノートを作るときは必ずテンプレートを使う。

```
99_system/templates/
├── meeting.md
├── person.md
├── company.md
├── project.md
├── insight.md
├── exploration.md
├── observation.md
└── moc.md
```

---

## プライバシーガードレール

- 個人プライバシー（家族・健康・宗教等）はトランスクリプトに出ても記録しない
- 主観評価（「優秀」「冷たい」等）ではなく観察事実のみ
- ネガティブ批評ではなく観察を書く
- 第三者の噂話は記録しない
- クライアント機密情報は Vault に書かない（または別 Vault に隔離する）

`person-enricher` の LLM プロンプトはこのガードレールを毎回確認する設計。
