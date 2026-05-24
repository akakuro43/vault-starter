---
name: meeting-summarizer
description: vault/00_inbox/meeting_transcripts/ にある未処理トランスクリプトを議事録化して 04_meetings/ に書き出す。15分おきの cron で起動するか、`/meeting-summarizer` で手動実行する
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [vault, meeting, transcript, summarization, japanese]
    category: vault
    requires_toolsets: [terminal]
---

# meeting-summarizer

> **Note**: このスキルは Hermes / Claude Code 等のホスト AI エージェントから呼ばれる前提で書かれています。
> LLM 推論 (議事録要約・分類判断) はホストが担当し、scripts は I/O のみ。
> 通知 ("Discord に配信" 等の記述) もホストの出力ルーティングを前提としています。
> パスは `./skills/`、`./vault/` 基準。詳細は [docs/skills-catalog.md](../../docs/skills-catalog.md) を参照。

Google Meet のトランスクリプトを構造化された議事録に変換し、Vault に蓄積するスキル。

## When to Use

次のいずれかに該当するとき：

- `./vault/00_inbox/meeting_transcripts/` 直下に `type: transcript` の md ファイルがある
- ユーザーが `/meeting-summarizer` で手動起動
- cron が 15 分ごとに起動

未処理トランスクリプトが 0 件なら何もせず終了する。

## Procedure

### 1. 未処理トランスクリプトを取得

```bash
python3 ./skills/meeting-summarizer/scripts/scan_inbox.py --pretty
```

JSON 配列が返る。各要素は `{ path, date, title, owner, drive_id, drive_filename }`。
古い順（date 昇順）に並んでいる。

### 2. 0 件なら早期終了

配列が空なら **`[SILENT] no transcripts to process`** だけ出力して終了。
それ以外の出力は不要。

### 3. 各トランスクリプトを順に処理

トランスクリプト 1 本につき以下を実行（古い順）。
1 本失敗しても次に進む（停止しない）。

#### 3.1 本文を読む

```bash
cat <transcript-path>
```

#### 3.2 client / project を二段で分類

```bash
python3 ./skills/meeting-summarizer/scripts/classify_project.py \
  --transcript <transcript-path> --pretty
```

戻り値は二段構造:

```json
{
  "client": {
    "slug": "ゴダイ",
    "name": "ゴダイ",
    "confidence": "high" | "medium",
    "matched_via": ["title:ゴダイ"],
    "candidates": [{...}, ...]
  } | null,
  "projects": [
    {
      "project": "godai-ai-training",
      "score": 95,
      "confidence": "high" | "medium" | "low",
      "reasons": [...],
      "client": "ゴダイ",
      "operator": "Xenkai",
      "status": "active",
      "scope": "client-filtered" | "all"
    },
    ...
  ]
}
```

- **client** は `03_companies/<slug>.md` の `name` + `aliases` と transcript の title/body を照合した結果。title hit → `high`、body のみ hit → `medium`、ヒットなし → `null`。
- **projects** は project 単位スコア（既存ロジック）。`confidence` は `high` (≥85) / `medium` (50-84) / `low` (<50)。
- **scope=client-filtered** は client がマッチしたため、その company の `projects:` リストに絞ってスコアしたことを示す。scope=all は全 project 対象。

#### 3.3 信頼度に応じた分岐（client と project は独立判定）

**client フィールド:**

| `client.confidence` | 採用方針 |
|---|---|
| **high** | `client: "[[<name>]]"` を採用 |
| **medium** | 本文を熟読して確信があれば採用、無ければ `unclassified` |
| **null (no match)** | `client: unclassified` |

**project フィールド:**

| `projects[0].confidence` | 採用方針 |
|---|---|
| **high** | 候補 1 位の project を採用。`project: "[[<slug>]]"` |
| **複数 high** | 高信頼が 2 件以上なら配列形式 `project: ["[[a]]", "[[b]]"]` |
| **medium** | 本文熟読の上で最適候補を判断、確信が持てなければ `unclassified` |
| **low / 候補なし** | `project: unclassified`（client が high でも、project は独立に unclassified にしてよい） |

新しいクライアント・新しい案件（`03_companies/` や `01_projects/` に存在しない）は **自分で Company / Project エンティティを作成しない**。
`unclassified` で書き、後段の vault-resolver スキルに委ねる。

**典型パターン**:
- client=high + project=high → 両方確定
- **client=high + project=low → client のみ確定、project は unclassified**（既存案件に紐付かない単発相談など）
- client=null + project=high → 既存案件にひも付くがクライアント未登録（vault-resolver に委ねる）
- client=null + project=low → 完全な unclassified

#### 3.4 議事録を生成

`./skills/meeting-summarizer/templates/meeting.md` の構造を**参照**する。
実例の値（"定例会" 等）は使わず、対象トランスクリプトの内容から自前で生成する。
templates/meeting.md 末尾の `<!-- Notes ... -->` セクションは**出力に含めない**。

**出力言語は日本語固定**。frontmatter の `description`、見出しだけでなく、本文の `サマリ` / `決定事項` / `ネクストアクション` / `未解決イシュー` / `観察事項` / `トピック別サマリ` も日本語で書く。固有名詞・ツール名・英語略語（Google Drive, Gemini, Claude, KPI 等）はそのまま使ってよいが、文・箇条書きの説明本文を英語にしない。OpenAI 系モデルなど英語に寄りやすいモデルを使う場合も、この制約を優先する。

frontmatter のフィールド:

| key | 値の決め方 |
|-----|----------|
| description | トランスクリプトを読んで命題的に 1 文で要約。**150 字以内・句点なし**（vault/CLAUDE.md スキーマ厳守） |
| type | `meeting` 固定 |
| date | トランスクリプト frontmatter の `date` と同じ |
| title | 会議の本質を表す具体的なタイトル（"定例会" のような曖昧名は避ける。`<会議の主要テーマ>` のような短い句に） |
| client | `client.confidence` が high/medium 確定なら `"[[<company slug>]]"`、ヒットなし or 確信なしなら文字列 `unclassified` |
| project | `projects[0].confidence` が high なら `"[[<project slug>]]"`、複数 high なら配列、それ以外は `unclassified`（client が high でも project だけ unclassified にしてよい） |
| participants | トランスクリプトから抽出した発話者を `"[[姓名]]"` のリストで |
| transcript | 元ファイル名のみ（拡張子なし）。例: `"[[2026-05-01_定例会]]"` |
| source | 現在の生成元 + モデルを併記。例: `hermes/qwen3.6:35b-a3b-mlx-bf16`。OpenAI 切替時は `hermes/openai:gpt-4o` |
| generated | 今日の日付（YYYY-MM-DD） |
| tags | トランスクリプトから自由語彙で 3〜7 個程度 |

本文セクション順（templates/meeting.md 参照）:

1. `# <タイトル>`
2. `## サマリ` — 2〜3 文。一覧で見て中身を思い出せる粒度
3. `## 参加者` — 役割・所属はトランスクリプトから読み取れれば併記、無理なら `- [[姓名]]` だけで OK
4. `## 決定事項` — 空なら `- （明示的な決定なし）` の 1 行
5. `## ネクストアクション` — `- [ ] <内容> — 担当: [[人物]] / 期限: YYYY-MM-DD`。担当・期限が読めなければ `— ` 以降を省略。空なら `- （明示的なアクションなし）`
6. `## 未解決イシュー` — `### 会議で発話されたもの` と `### AIによる分析` の 2 サブセクション。両方空ならセクションごと省略。片方だけ空なら空の方のみ省略
7. `## 観察事項` — 議論の流れの変化、個人の発言傾向、決定/アクション/イシューに当てはまらないが残す価値あるもの。なければセクションごと省略
8. `## トピック別サマリ` — `### <トピック名>` で複数化。1 トピックのみなら `###` を省略して `##` 直下に箇条書き／長文。形式自由

#### 3.5 04_meetings/ に書き出し

ファイル名規約:
```
./vault/04_meetings/<date>_<sanitized_title>.md
```

`<sanitized_title>` は OS 不可文字（`<>:"/\\|?*` と制御文字）を除去したもの。
同名ファイルが既に存在する場合は `_2`, `_3` とサフィックスで衝突回避。

書き出し後、本文英語化の簡易チェックを実行する。NG の場合は議事録本文を日本語に修正してから次工程へ進む。

```bash
python3 ./skills/meeting-summarizer/scripts/check_meeting_language.py \
  ./vault/04_meetings/<date>_<sanitized_title>.md --pretty
```

書き出し方法（terminal ツール）:
```bash
cat > "./vault/04_meetings/2026-05-01_xxxx.md" <<'EOF'
---
description: ...
...
---

# xxxx

...
EOF
```

#### 3.6 Project の last_activity 更新（高信頼時のみ）

`confidence: high` で project が確定した場合のみ実行:

```bash
python3 ./skills/meeting-summarizer/scripts/update_last_activity.py \
  --project <slug> --date <YYYY-MM-DD>
```

medium / low / unclassified では実行しない。
複数 project に該当する場合は、各 high project に対して実行する。

#### 3.7 トランスクリプトを退避

議事録の書き出しが**成功した場合のみ**実行:

```bash
python3 ./skills/meeting-summarizer/scripts/move_to_processed.py \
  --path <transcript-path>
```

退避先は `00_inbox/meeting_transcripts/processed/YYYY-MM/`。

#### 3.8 action items 抽出とタスク化 (T0116 + T0129 + T0177 + T0178)

議事録の書き出しが成功し、frontmatter に `tasks_extracted_at` が未設定の場合のみ実行する。以下の 3 段は **順序が必須** (§3.8.2 は §3.8.1 の出力に、§3.8.3 は §3.8.1 と §3.8.2 両方の出力に依存)。並行実行・skip は禁止。

##### 3.8.1 action items 抽出

`extract_action_items.py` を単体で動かして JSON を `./vault/.scratch/action_items_<meeting_stem>.json` に出力する。`<meeting_stem>` は議事録ファイル名から拡張子を外したもの。

```bash
mkdir -p ./vault/.scratch/
python3 ./skills/meeting-summarizer/scripts/extract_action_items.py \
  <meeting-md-path> --pretty > ./vault/.scratch/action_items_<meeting_stem>.json
```

##### 3.8.2 owner 推論（エージェント駆動、T0129）

議事録本文と `./vault/.scratch/action_items_<meeting_stem>.json` を読み、各 action item に対し以下の 3 つを判定する:

- `owner`: `endo` | `other` | `unclear`
  - `endo`: Endo が自分で実行するアクション、または Endo がリードして関係者と動くもの
  - `other`: 議事録の参加者（Endo 以外）が自分のマシン / 領域で自走するもの、Endo の関与が不要なもの
  - `unclear`: 文脈から owner を一意に決められないもの（Endo の朝 brief で人手 review）
- `purpose`: Markdown 1-2 行（このタスクが達成したいゴール・もたらしたい変化）
- `premise`: Markdown bullet 3-5 行（現状認識・障害・活かせる構造）
- `acceptance_criteria`: Markdown bullet 2-4 個（DoD）

出力 JSON スキーマ:

```json
[
  {
    "item_content": "<extract_action_items.py の content と一致、strip 済み>",
    "owner": "endo|other|unclear",
    "purpose": "<Markdown 本文 1-2 行>",
    "premise": "<Markdown bullet 列 3-5 行>",
    "acceptance_criteria": "<Markdown bullet 列 2-4 個>",
    "reasoning": "<判定根拠 1-2 文、デバッグ用>"
  }
]
```

出力先: `./vault/.scratch/owner_inferences_<meeting_stem>.json`

**注**: `item_content` は `extract_action_items.py` の JSON 出力 `content` フィールドからそのまま転記し、`.strip()` のみ適用してください（言い換え・要約・句読点の補正は行わない）。マッチング失敗時はその item は現行（T0116）挙動にフォールバックします。

`purpose` / `premise` / `acceptance_criteria` は判定できない場合 **`null` を使う**（空文字列 `""` は使わない）。

`create_tasks_from_actions.py` 側の各 null 時の挙動:
- `purpose=null` → 「## 目的（なぜやるか）」に `// 議事録から推論不可。朝 review で記入してください` を埋める
- `premise=null` → 「## 前提（いま捉えている状況）」に `// 議事録から推論不可` を埋める
- `acceptance_criteria=null` → 「## 受け入れ基準（DoD）」に `// /plan-task で記入されます` を埋める

**purpose は議事録の文脈から最も妥当な推測を返してください。完全な確信が持てなくても 1 文書く。** null は議事録に該当 action item の文脈が一切ない場合のみに限定する。

推論に失敗した場合は **その議事録を skip し、`tasks_extracted_at` を立てず、次のトランスクリプトへ進む**（次回 cron で自動リトライ）。

##### 3.8.3 タスク起票

`create_tasks_from_actions.py` に `--action-items` と `--owner-inferences` の両方を渡す。

```bash
python3 ./skills/meeting-summarizer/scripts/create_tasks_from_actions.py \
  --meeting <meeting-md-path> \
  --action-items ./vault/.scratch/action_items_<meeting_stem>.json \
  --owner-inferences ./vault/.scratch/owner_inferences_<meeting_stem>.json \
  --pretty
```

処理内容（T0116 ベース + T0129 + T0177 拡張）:

1. 議事録の `## ネクストアクション` セクションを正規表現でパース（既存）
2. owner 推論結果を `item_content` でマップし、各 action item を分岐:
   - `owner=other` → タスク化スキップ、議事録の元行に逆リンクを付けない
   - `owner=endo` / `owner=unclear` → 起票。タスクカード本文に top-level セクションで `## 目的（なぜやるか）` / `## 前提（いま捉えている状況）` / `## 受け入れ基準（DoD）` を差し込み（各 null フィールドは規定プレースホルダで埋める）
   - `--owner-inferences` 未指定または item_content マッチしない場合 → 現行（T0116）と同一挙動 (purpose / premise / acceptance_criteria すべて null 扱い)
3. 議事録側に逆リンク追記（既存、owner=other は対象外）
4. 全件成功時のみ議事録 frontmatter に `tasks_extracted_at` 追記（既存、冪等性ガード）

出力 JSON の `created` / `failed` / `skipped` 件数を §4 完了報告に含める。

action item が 0 件の議事録は `tasks_extracted_at` を立てて完了扱い（空抽出も処理済み）。

##### 3.8.4 Scratch クリーンアップ (推奨)

タスク起票が成功し議事録 frontmatter に `tasks_extracted_at` が立った後は、
`./vault/.scratch/action_items_<meeting_stem>.json` と
`./vault/.scratch/owner_inferences_<meeting_stem>.json` を削除してよい。

ディレクトリは vault `.gitignore` で除外されているため残しても git 汚染はないが、
disk 容量を抑えたい場合は cron 終了前に rm すること:

```bash
rm -f ./vault/.scratch/action_items_<meeting_stem>.json \
      ./vault/.scratch/owner_inferences_<meeting_stem>.json
```

失敗してもタスク化結果は既に永続化されているので、cleanup の失敗は無視してよい。

### 4. 完了報告

Discord 通知を読む人が状況判断できるよう、**日本語の短い運用レポート**として出力する。議事録本文は出さない。

必ず含める内容:

1. **見出し**: `📝 Meeting Summarizer レポート`
2. **処理結果**: 処理件数、成功件数、失敗件数
3. **生成した議事録**: 各トランスクリプトごとに、元タイトル/日付、分類結果、生成先ファイルを 1〜2 行で示す
4. **タスク化件数 (T0116 + T0129)**: §3.8 で起票したタスク件数と skip 件数。例: `タスク化: 3 件起票 / 2 件 skip（他者専属）`、抽出 0 件なら `タスク化: 0 件`、抽出失敗時は `タスク化: 失敗 1 件（次回 cron で再試行）`
5. **人の確認が必要なもの**: `unclassified` がある場合は「案件分類が未確定なので確認が必要」と明記する。draft タスクが生成された場合は「翌朝の joshu-morning-brief で要 review」と添える
6. **次に見る場所**: `04_meetings/...` のパス、必要なら `client/project: unclassified` を直す旨

`high-confidence` や `unclassified` のような内部ラベルだけで終わらせず、意味を日本語で添える。

例:

```markdown
📝 Meeting Summarizer レポート

2件のトランスクリプトを議事録化しました。
タスク化: 全 5 件起票 / 3 件 skip（他者専属）

## 生成した議事録
- 2026-05-08「採用支援部ヒアリング」
  - 出力先: `04_meetings/2026-05-08_採用支援部の就活学生管理アプリ開発方針協議.md`
  - 分類: 未分類（既存Projectに高信頼で紐づけられませんでした）
  - タスク: T0118 / T0119 / T0120 を draft で起票 / 2 件 skip（他者専属）
  - 確認: frontmatter の `client` / `project` が `unclassified` なら、人が該当案件に修正してください
- 2026-05-09「AtomicFlow 開発方針確認」
  - 出力先: `04_meetings/2026-05-09_AtomicFlow開発方針確認.md`
  - 分類: AtomicFlow（高信頼）
  - タスク: T0121 / T0122 を draft で起票 / 1 件 skip（他者専属）

## 要確認
- 1件は案件分類が未確定です。議事録の内容を見て、既存案件へ紐づくか確認してください。
- 5 件の draft タスクが追加されました。翌朝の joshu-morning-brief で内容 review をお願いします。
```

## Pitfalls

### 出力品質

- **本文は日本語固定**: トランスクリプトが日本語中心なら、議事録本文も日本語で書く。見出しだけ日本語で本文が英語になる状態は失敗扱い
- **description の 150 字制限**: 厳守。超えそうな場合は内容を絞る（複数論点があっても1命題に圧縮）
- **句点なし**: description には `。` を使わない（命題形・体言止め）
- **タイトルは具体的に**: `定例会` `MTG` のような汎用語ではなく、`研修運用刷新と新規AI事業立ち上げ協議` のように内容を表現
- **templates の値をコピーしない**: templates/meeting.md は構造参照用。"千葉宏輝"・"ゴダイ" などの実例値を勝手に出力に持ち込まない
- **日付は半角数字固定**: 本文・タイトル・action item 行・description のすべてで日付は半角アラビア数字で書く。`5月28日` / `2026-05-28` / `5/28` は OK、`五月二十八日` / `五月二十八日` のような漢数字表記は禁止（vault/CLAUDE.md「数字は半角」規約）。トランスクリプトが漢数字で書いていても議事録では半角に正規化する

### Vault 規約

- **新規人物**: 02_people/ にいない人物も `[[姓名]]` の wikilink で書く。自分で 02_people/<姓名>.md を**作成しない**（vault-resolver スキルに委ねる）
- **新規 client / project**: `03_companies/` にない会社、`01_projects/` にない案件は `unclassified`。自分で Company / Project エンティティを**作成しない**（vault-resolver に委ねる）
- **04_meetings/ 直接書きの例外**: 通常 vault/CLAUDE.md は「inbox 経由必須」を求めるが、議事録はこのスキルが構造化済みで生成するため直接書きが許可されている
- **Notes セクション混入**: templates/meeting.md 末尾の `<!-- Notes ... -->` は出力に**絶対に含めない**

### 副作用の冪等性

- **last_activity は high のみ**: 中信頼以下では更新しない。間違った project に書き込むより未更新の方が安全
- **move は成功時のみ**: 議事録書き出しが失敗したらトランスクリプトは inbox に残す（次回 cron で再試行）
- **エラーで全体停止しない**: 1 本のトランスクリプト処理が失敗しても、ログに残して次へ進む
- **tasks_extracted_at は全件成功時のみ (T0116)**: 部分失敗時は flag を立てず、次回 cron で再試行。抽出 0 件の場合も flag を立てて完了扱い（空処理を「処理済み」と認識させる）
- **既存 wikilink への副作用なし**: §3.8 は議事録に `→ [[T####]]` を追記するのみ、既存セクションを書き換えない

### owner 推論パイプライン

- **owner 推論ステップ (Step 3.8.2) skip 漏れリスク (T0129)**
  Step 3.8.2 を経由しないと `--owner-inferences` が `create_tasks_from_actions.py` に渡されず、`owner=other`（他者専属）の判定が行われない。結果として全 action item が一律にタスク化され、Endo のアクションキューが他者専属タスクで埋まる。SKILL.md の 3 段パイプラインを順に実行し、Step 3.8.3 のコマンドで `--owner-inferences` を必ず渡してください。推論に失敗した場合は議事録 1 本ごと skip して次のトランスクリプトへ進む（`tasks_extracted_at` を立てない、次回 cron で自動リトライ）。

### 並行実行・レース

- cron は 15 分ごと、各実行は独立セッション
- scan_inbox.py の結果取得後、処理中に新ファイルが届く可能性あり → 次回サイクルで拾われるので問題なし
- 同じファイルを 2 回処理しないよう、move_to_processed が完了するまで scan_inbox の結果を信じない

## Verification

各トランスクリプトの処理完了後、以下を自己確認する:

1. **議事録ファイルが書き出されている**:
   `ls ./vault/04_meetings/<date>_<title>.md` で存在確認

2. **出力言語が日本語である**:
   - frontmatter の `description` だけでなく、本文の各セクションも日本語で書かれている
   - 英語の文・箇条書きが連続していない（固有名詞・ツール名・略語は除外）
   - `Summary`, `Decision`, `Next Action` 相当の内容が英語文になっていたら修正または失敗扱いにする
   - 書き出し後、簡易チェックを実行する:
     ```bash
     python3 ./skills/meeting-summarizer/scripts/check_meeting_language.py \
       ./vault/04_meetings/<date>_<title>.md --pretty
     ```
     exit code が 1 の場合は、検出行を確認して本文を日本語に修正してから再実行する

3. **frontmatter 必須フィールドが揃っている**:
   - `description` / `type: meeting` / `date` / `title` / `transcript` / `source` / `generated` / `tags`
   - description が 150 字以内・句点なし

4. **日付は半角数字である**:
   - 本文・action item 行・description に漢数字日付（`五月二十八日` 等）が含まれていないか確認
   - 検出コマンド:
     ```bash
     grep -E "[一二三四五六七八九十]月[一二三四五六七八九十]+日" \
       ./vault/04_meetings/<date>_<title>.md
     ```
   - ヒットがあれば該当箇所を `5月28日` / `2026-05-28` 形式に修正してから次工程へ進む

5. **本文の必須セクションが存在**:
   - `## サマリ` / `## 参加者` / `## 決定事項` / `## ネクストアクション` / `## トピック別サマリ`

6. **トランスクリプトが退避済み**:
   `00_inbox/meeting_transcripts/<date>_<title>.md` が無く、
   `00_inbox/meeting_transcripts/processed/YYYY-MM/<date>_<title>.md` がある

7. **last_activity 更新（high のみ）**:
   `grep "^last_activity:" 01_projects/<slug>/<slug>.md` で当該 date 以上になっている

いずれか失敗していれば、エラーをログに記録して次のトランスクリプトへ進む（停止しない）。
