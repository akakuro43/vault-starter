---
name: person-enricher
description: 04_meetings/ の議事録と元トランスクリプトから人物の観察を抽出し、02_people/<人物>/ 配下にログ追記・プロファイル合成する。毎日 04:00 cron 起動、または `/person-enricher` で手動実行
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [vault, people, profiling, japanese]
    category: vault
    requires_toolsets: [terminal]
---

# person-enricher

> **Note**: このスキルは Hermes / Claude Code 等のホスト AI エージェントから呼ばれる前提で書かれています。
> LLM 推論 (観察抽出・プロファイル合成) はホストが担当し、scripts は I/O のみ。
> パスは `./skills/`、`./vault/` 基準。詳細は [docs/skills-catalog.md](../../docs/skills-catalog.md) を参照。

議事録とトランスクリプトを「人物視点」で再編成し、各人物のプロファイルを継続的にエンリッチするスキル。

ハイブリッド戦略:
- **観察ログ**: 会議ごとの観察を時系列で append（生データ蓄積）
- **プロファイル**: 観察ログから定期的に LLM 合成（要約された理解）

> **2026-05-24 — 02_people/ の唯一の書き手 + per-person ディレクトリ構造**
> build_people.py の退役に伴い、`02_people/<人物>/` 配下の書き換え責任はこのスキルに一本化された。
>
> ディレクトリ構造（01_projects/ と同じ慣習）:
> ```
> 02_people/<人物>/
>   ├── <人物>.md          ホームノート（基本情報 + プロファイル + 参加したミーティング）
>   └── observations.md    観察ログ（時系列の生データ蓄積）
> ```
>
> update_person_note.py がホームノートの meeting_count / last_meeting / updated / **related_projects** /
> 基本情報 table の MTG参加数・最終MTG・関連PJ セル・## 参加したミーティング を維持し、
> 観察ログ entry は observations.md に append する。
>
> synthesize_profile.py は observations.md を読んでホームノートの ## プロファイル セクションを置換する。
>
> 新規人物の skeleton 作成はこのスキルでは行わない — 議事録に [[姓名]] が現れて 02_people/<姓名>/ に未登録なら skip して vault-resolver に委ねる。

## When to Use

次のいずれか：

- cron が毎日 04:00 に起動（meeting-summarizer の後）
- ユーザーが `/person-enricher` で手動起動

未処理議事録が 0 件 かつ プロファイル再生成対象が 0 件なら `[SILENT]` で終了。

## Procedure

### 1. 未処理議事録のスキャン

```bash
python3 ./skills/person-enricher/scripts/scan_meetings_to_process.py --pretty
```

`state.json` の `last_processed_meeting_date` 以降で、**新形式（`participants:` frontmatter あり）**の議事録のみ JSON で返る。

旧形式（plain text 参加者）は対象外。

### 2. 早期終了判定

未処理議事録 0 件 かつ 後続のプロファイル再生成対象も 0 件なら：

```bash
python3 ./skills/person-enricher/scripts/update_state.py --action list-pending-synthesis
```

両方とも空なら、最終応答は `[SILENT] no meetings to process` のみ。

### 3. 各議事録 × 各参加者の処理

未処理議事録 1 本ごとに：

#### 3.1 議事録本文を読む

```bash
cat <meeting-path>
```

#### 3.2 元トランスクリプトを読む（あれば）

`transcript: "[[2026-MM-DD_xxx]]"` の値からファイル名を抽出し、`00_inbox/meeting_transcripts/processed/YYYY-MM/<filename>.md` を読む。
存在すれば本文（生発言ログ）を取得。**人物の発言ニュアンスはここから読み取る**。

存在しなければ議事録のみで観察を生成（情報量は限定的）。

#### 3.3 各 participant について処理

participants 配列の各 wikilink（例: `"千葉宏輝"`）について以下を実行：

##### 3.3.a 02_people/ にいるか確認

```bash
ls ./vault/02_people/<person>/<person>.md
```

存在しなければ **skip**。後段の vault-resolver に委ねる。skip カウントを保持して報告に含める。

##### 3.3.b 観察を LLM で抽出

トランスクリプトと議事録の文脈から、その人物について以下を JSON で生成:

**必須項目:**
- `key_statements`: その会議でのその人の主要な発言（要約）の配列
- `interests`: 関心を示したトピック（短い語彙）
- `role`: 会議内での役割（"提案者" / "ファシリテーター" / "質問者" / "反対者" / "観察者" など）
- `issues_raised`: その人が「これが課題」と発した内容

**任意項目（読み取れた範囲で）:**
- `relations`: 他者との関係観察（誰と協調 / 衝突 / 補完したか）
- `expertise_signals`: 専門知識を示した発言や視点

参加者全員に書く必要はない。**観察に値する内容がある人物のみ**。発言が少なくて観察できる素材が無ければ skip して良い。

##### 3.3.c 02_people/<人物>/ に書き込み

```bash
python3 ./skills/person-enricher/scripts/update_person_note.py \
  --person <name> \
  --meeting-date <YYYY-MM-DD> \
  --meeting-title "<title>" \
  --meeting-link "[[<filename>]]" \
  --meeting-project '<project>' \
  --observation-json '<json>'
```

`--meeting-project` には議事録 frontmatter の `project:` 値を渡す。`"[[slug]]"` / `"[[a]],[[b]]"`（複数 high のとき） / `"unclassified"`（除外される） / 省略可。

このスクリプトは決定論的に以下を実行:
- ホームノート (`02_people/<person>/<person>.md`):
  - frontmatter の `meeting_count` をインクリメント
  - `last_meeting` を更新（より新しければ）
  - `updated` を今日に
  - `related_projects` に議事録 project を union 追加（unclassified は除外、重複排除）
  - `## 参加したミーティング` リストに wikilink を追加
  - `## 参加したミーティング（N件）` の N を更新
  - 「基本情報」table の MTG参加数 / 最終MTG / 関連PJ セルを更新
- 観察ログ (`02_people/<person>/observations.md`):
  - `## 観察ログ` セクションに entry を append（ファイル・セクションが無ければ自動作成）

##### 3.3.d state の observation count をインクリメント

```bash
python3 ./skills/person-enricher/scripts/update_state.py \
  --action increment-observation --person <name>
```

### 4. 議事録処理完了後

```bash
python3 ./skills/person-enricher/scripts/update_state.py \
  --action mark-meeting-processed --date <最後に処理した議事録の date>
```

これで翌日以降は同じ議事録が再処理されない。

### 5. プロファイル再生成判定

```bash
python3 ./skills/person-enricher/scripts/update_state.py \
  --action list-pending-synthesis --pretty
```

**観察 3 件以上 蓄積 OR 前回合成から 7 日以上経過** の人物が JSON 配列で返る。

> **Cron prompt の閾値指定を優先する**: 定期ジョブ側で「観察 5 件蓄積 OR 7 日経過」のように明示されている場合は、デフォルト値ではなく `--threshold-count 5 --threshold-days 7` を必ず付ける。早期終了判定でも同じ閾値を使い、処理後の pending 確認も同じ引数で行う。

各対象について以下を実行:

#### 5.a 観察ログを読む

```bash
cat ./vault/02_people/<person>/observations.md
```

`## 観察ログ` セクションを取り出して LLM に渡す。

#### 5.b プロファイル本文を LLM 合成

**10 セクション構成**で生成する。stakeholder profiling と CRM relationship intelligence の dimension をベースに、Endo が「次回の会議で具体的にどう協働するか」を予測できる粒度に設計。

```markdown
### 役割と立場
- 議論における立場（意思決定者 / 影響者 / 実行者 / 専門家 / 観察者）
- 関わる案件・領域での立ち位置、意思決定権限の範囲

### 強い関心領域
- 観察ログから繰り返し現れる関心を抽出

### 専門性・知見
- expertise_signals の蓄積から推測される領域、具体的な経験・実績の例

### 動機・ドライバー
- 何を達成したい人か（事業成果 / 学び / 組織貢献 / 個人成長 など）
- 仕事に対する価値観や優先順位

### 懸念・課題視点
- issues_raised の蓄積から見える「この人が問題視する領域」
- 慎重になるトピック・避けようとするリスク

### 意思決定スタイル
- 速さ（即決 / 慎重）
- 重視する判断材料（データ / 直感 / 合意 / 経験）
- リスク許容度

### コミュニケーションパターン
- role の分布、発言の傾向（提案 / 質問 / 整理 / 反対）
- 議論の進め方の癖

### 関係性
- 他者との協調パターン（誰と組みやすいか、補完関係）
- Endo との協働パターン（依頼の方向、信頼レベル）

### 直近の文脈
- 直近 3-5 件の観察から見える状況変化
- 今 active な案件・優先事項

### 未確認・仮説
- まだ観察できていない領域
- 仮説として保留している観察（次回会議で確認したいこと）
```

**ルール**:
- 合成は**観察ログという事実ベース**で。ファイルに書き込むのは確実な傾向のみ
- 観察が薄いセクションは省略せず `（観察不足）` または `（未確認）` と明示
- 「直近の文脈」は observations.md の末尾エントリを優先参照
- 「未確認・仮説」は積極的に書く — 次回会議で意識的に観察できるよう手がかりを残す
- 仮説には `（仮説）` の注記を付ける。確証のある記述と分離する

#### 5.c プロファイル書き込み

```bash
python3 ./skills/person-enricher/scripts/synthesize_profile.py \
  --person <name> \
  --observation-count <観察ログの総 entry 数> \
  --profile-content -
```

stdin にプロファイル本文を流す。スクリプトが `## プロファイル` セクションを置換 or 新規挿入する（基本情報の直後）。

**Hermes 実行時の推奨**: `printf %s ... | python3 ... --profile-content -` のような shell quoting 依存のパイプは、長い日本語 Markdown で失敗時の stderr が見えにくく、誤って実ノートのプロファイルをテスト文で上書きするリスクもある。`execute_code` / Python `subprocess.run([...], input=profile_content, text=True, capture_output=True)` で argv と stdin を分離し、returncode/stdout/stderr を確認してから `mark-synthesized` する。スクリプト疎通確認が必要な場合は実人物ノートではなく一時コピーで行う。

#### 5.d state の synthesis を更新

```bash
python3 ./skills/person-enricher/scripts/update_state.py \
  --action mark-synthesized --person <name>
```

これで `observations_since_last` が 0 にリセットされ、次の閾値判定が機能する。

### 6. 最終応答 = Discord に配信されるメッセージ

verification や中間ログを最終応答に含めない。
下記フォーマットを直接出力する。

#### 6-A. 何も処理しなかったとき

```
[SILENT] no meetings to process
```

#### 6-B. 処理対象があったとき

```
👥 人物プロファイル更新レポート (YYYY-MM-DD)

📊 実行サマリ
• 処理議事録: N件
• 観察ログ追加: 計M件 / X名の人物
• プロファイル再生成: K名
• スキップ（02_people/ 未登録）: L名 → vault-resolver に委譲

──────

主要な観察対象:
• [[千葉宏輝]]: 観察 3件追加（プロファイル更新）
• [[岸田憲治]]: 観察 1件追加
• [[渡邉隆]]: 観察 2件追加

詳細 state: ops/person-enricher/state.json
```

ルール:
- 各人物 1 行に観察追加件数とプロファイル更新有無を明示
- 「主要な観察対象」は 観察追加 1 件以上の人物のみ列挙
- スキップした未登録人物は名前を出さない（vault-resolver で個別通知される）
- 月曜判定不要（毎日 cron）

絶対禁止：
- 観察ログの中身を Discord に貼る（プライバシー）
- プロファイル本文を Discord に貼る（同上）
- 「verification 完了」「これから生成します」のような前置き

## Pitfalls

### プライバシーガードレール

**書く:**
- 仕事上の発言・関心・専門性
- 役割（提案者・質問者など機能的な観察）
- コミュニケーションパターン（即決/慎重など）
- 他者との関係（協調/補完など事実ベース）

**書かない:**
- 個人プライバシー（家族・健康・宗教等）— 仮にトランスクリプトに出ても無視
- 主観評価（「優秀」「冷たい」等）— 観察事実のみ可
- ネガティブ批評 — 評価ではなく観察を書く
- 第三者の噂話 — 当事者に確認できない情報は記録しない

LLM が観察抽出するときに**この方針を毎回確認**する。

### 旧形式議事録のスキップ

`participants:` frontmatter が無い議事録（fetch_mtgs.py 由来の 130+件）は処理対象外。
scan_meetings_to_process.py が自動でフィルタする。

旧形式議事録の参加者は plain text（"千葉" など）で姓名フルマッチが取れないため、
誤紐付けリスクを避けて v1 ではスキップ。将来 migration script で対応。

### 新規人物の自動作成禁止

02_people/ に存在しない参加者は **skip**。自分で `02_people/<人物>/` ディレクトリを**作成しない**。
未解決リンクは vault-resolver スキルが Discord で確認・登録を促す。

### 観察の品質

- 「観察に値する素材がない参加者」は skip して良い（全員に書く必要なし）
- key_statements は要約。元発言の長文をそのまま貼らない
- issues_raised は「その人が問題と認識した」内容のみ。会議全体の論点ではない

### バックログ大量処理時の実行方法

未処理議事録が数十件ある場合、1ファイルずつ手作業で読むと context と時間を浪費しやすい。Hermes では `execute_code` で以下をまとめて行うと安定する。

1. `scan_meetings_to_process.py` の JSON を読み込む
2. 各議事録の `## 観察事項`・`## ネクストアクション` を抽出し、参加者名・姓・既知 alias で候補行を拾う
3. 02_people/<姓名>/<姓名>.md に存在する人物だけ `update_person_note.py --observation-json -` に JSON を stdin で渡す
4. 成功した人物だけ `update_state.py --action increment-observation` する
5. 最後に最大 meeting date で `mark-meeting-processed` する
6. `list-pending-synthesis` → `synthesize_profile.py --profile-content -` → `mark-synthesized` を、returncode/stdout/stderr 確認つきで実行する

注意: この高速経路は、議事録側に人物別の観察や担当タスクが既に十分抽出されている場合の fallback。発言ニュアンスが重要な会議や観察が薄い会議では、元トランスクリプトを読む通常手順を優先する。

### プロファイル再生成の判断

- 3 件溜まる前に 7 日経過 → 経過日数で再生成（少ない観察でも更新）
- 3 件溜まる → 観察カウントで再生成（早めに更新）
- どちらも満たさない → スキップ

過剰な再生成は LLM コストを増やすだけ。条件を素直に守る。

### state の冪等性

- last_processed_meeting_date は1日ごとに前進
- 同じ議事録を 2 回処理しないよう、scan の date 比較は `>` 厳密
- mark-meeting-processed は最後に処理した議事録の date で実行

### 副作用の範囲

書き換える対象は **02_people/<人物>/** 配下と **ops/person-enricher/state.json** のみ。
04_meetings/ や 00_inbox/ は読み取り専用。01_projects/ は触らない。

## Verification

各実行の自己確認（**内部 reasoning。最終応答に含めない**）：

1. **処理した議事録数 vs scan 件数の整合性**
2. **state.json の last_processed_meeting_date が前進している**
3. **02_people/<人物>/<人物>.md の整合性**:
   - frontmatter `meeting_count` と「基本情報」table の MTG参加数 と「## 参加したミーティング（N件）」の N が一致
   - frontmatter `last_meeting` と table 「最終MTG」が一致
4. **プロファイル再生成された人物の `observations_since_last` が 0 にリセットされている**
5. **副作用なし**: 02_people/ と state.json 以外を変更していない
6. **最終応答のフォーマット**: ステップ 6 のフォーマット遵守、verification ログ混入なし
