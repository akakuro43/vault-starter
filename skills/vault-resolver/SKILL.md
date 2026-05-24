---
name: vault-resolver
description: vault 全体の未解決 wikilink（02_people / 01_projects に存在しない人物・案件）を検出して候補と一緒に Discord にレポートする。毎日 03:00 cron 起動、または `/vault-resolver` で手動実行
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [vault, resolver, discord, japanese]
    category: vault
    requires_toolsets: [terminal]
---

# vault-resolver

> **Note**: このスキルは Hermes / Claude Code 等のホスト AI エージェントから呼ばれる前提で書かれています。
> LLM 補正 (信頼度補正・concept 再分類) はホストが担当し、scripts は I/O のみ。
> 通知 ("Discord に配信" の記述) もホストの出力ルーティングを前提としています。
> パスは `./skills/`、`./vault/` 基準。詳細は [docs/skills-catalog.md](../../docs/skills-catalog.md) を参照。

vault 全体に散在する「未解決 wikilink」を検出し、既存エンティティとの類似度から候補を推測し、判断を仰ぐスキル。

## When to Use

次のいずれか：

- cron が 03:00 に起動（毎日）
- ユーザーが `/vault-resolver` で手動起動

ただし通知の出し分けがある：

- **新規未解決リンク**: 毎回通知
- **既存 pending（過去に通知済み）**: 月曜の朝のみリマインド通知

未解決リンクが 0 件なら何もせず `[SILENT]` で終了。

## Procedure

### 1. 未解決リンクのスキャン

```bash
python3 ./skills/vault-resolver/scripts/scan_unresolved.py
```

JSON 配列が返る。各要素は `{ link, kind, appearances }`。`kind` は `person` / `project` / `unknown`。
出現箇所 (`appearances`) は file・line・context を含む。

### 2. 各リンクに候補を付与

`kind == person` / `kind == project` / `kind == concept` のリンクごとに：

```bash
python3 ./skills/vault-resolver/scripts/suggest_candidates.py \
  --link <link> --kind <kind> --top 3
```

JSON の `[{ name, confidence, reasons }, ...]` が返る。
`confidence` は normalized_match (0.95) / Levenshtein (0.45–0.85)。

候補プール:
- `person` → 02_people/ 配下の type: person ノート
- `project` → 01_projects/<slug>/<slug>.md (type: project)
- `concept` → 06_knowledge/{insights,frameworks,references}/ 配下の `.md` ファイル

`kind == unknown` は候補推測しない（候補リストは空配列）。

### 3. LLM 文脈判断による信頼度補正

各リンクの `appearances` に書かれた**周辺コンテキスト**を読んで、候補の信頼度を補正する。

例:
- 議事録 A の参加者欄に `[[山田 太郎]]` と `[[品川武利]]` が並んでいる
- 候補 `[[山田太朗]]` が score-based では 0.85
- LLM が「同じ会議に品川武利が出ている = ゴダイ案件」と気づき、`[[山田太朗]]` がゴダイ関係者であれば信頼度を **+0.05〜0.1** 程度補正する

ただし**既存 score を大きく覆さない**こと。LLM 補正は穏やか（±0.10 まで）。

候補が 0 件のリンクは「**新規エンティティの可能性**」として扱う。LLM 補正なし。

### 4. queue への登録

scan + suggest + LLM 補正の結果を JSON 配列にまとめて、stdin 経由で update_queue に流す：

```bash
echo '<items_json>' | python3 ./skills/vault-resolver/scripts/update_queue.py \
  --action add-pending --items-json -
```

`items_json` の各要素は `{ link, kind, appearances, candidates }`。

`update_queue` は内部で：
- 既に resolved / dismissed 済みのリンクは skip
- 既に pending のリンクは appearances 統合 + candidates 更新
- 新規は新規 ID を発行して pending に追加

### 5. 通知ポリシー判定

```bash
date +%u   # 1=月曜, 2=火曜, ..., 7=日曜
```

- **新規 pending**（`notified_at == null`） → **必ず通知**
- **既存 pending**（`notified_at != null`） → **月曜のみ通知（リマインダ）**

新規 pending を取得：
```bash
python3 update_queue.py --action list-pending --unnotified
```

既存 pending（月曜のみ）：
```bash
python3 update_queue.py --action list-pending | jq '[.[] | select(.notified_at != null)]'
```

### 6. notified_at の更新

新規 pending を通知 **する前に**、それらの ID を `mark-notified` で記録する：

```bash
python3 update_queue.py --action mark-notified --ids "p_xxx,p_yyy,p_zzz"
```

（順序注意: ステップ7で Discord 出力する前に notified を立てる。出力後だと cron 失敗時に再通知されない問題が出るため、先に立てる方針）

### 7. 最終応答 = Discord に配信されるメッセージ

**重要: このステップの「最終応答」がそのまま Discord に配信されます。**

verification の経過、中間ログ、「これから生成します」のような前置きは **絶対に最終応答に含めない**。
下記フォーマットそのものを **直接** 最終応答として出力する。

#### 7-A. 通知対象が 0 件のとき

最終応答は次の1行のみ：

```
[SILENT] no unresolved links to notify
```

#### 7-B. 通知対象が 1 件以上のとき

下記フォーマットを最終応答とする（変数部分は実データで置き換える）:

```
🔍 Vault 未解決リンク レポート (YYYY-MM-DD)

📊 実行サマリ
• 未解決検出: N件（person:X, project:Y, concept:W, unknown:Z）
• queue: 新規A件 / 更新B件 / 解決済スキップC件 → pending 計T件
• 通知: 新規D件（リマインダE件）   ← 月曜以外はリマインダE=0

──────

新規未解決リンク: D件

【人物】X件
• [[link]] — 出現: <file_path> ほかN件
  候補: [[candidate]] (XX% / <reason>)   ← 候補ありの場合
  候補なし（新規の可能性）                ← 候補なしの場合
  → <推奨アクション>

【Project】Y件
• ...

【概念】W件
• [[link]] — 出現: <file_path> ほかN件
  候補: [[candidate]] (XX% / <reason>)   ← 06_knowledge/ 既存ノートから
  候補なし（新規の可能性）                ← 候補なしの場合
  → 既存 insight への alias or 新規 atomic note 作成

【その他/判定不能】Z件
• [[link]] — 出現: <file_path>
  → 文脈確認後に excluded.txt に追加 or エンティティ作成

— 月曜リマインダ —      ← 月曜のみ。それ以外の曜日は出さない
既存 pending 未対応: K件
（個別の link は省略。詳細は ops/resolver/queue.json）

詳細キュー: ops/resolver/queue.json
```

実行サマリの数値の出処:

| 項目 | データ源 |
|------|---------|
| 未解決検出 N / person X / project Y / concept W / unknown Z | scan_unresolved.py の出力 JSON を集計 |
| queue 新規 A / 更新 B / スキップ C / 計 T | update_queue.py --action add-pending の出力 JSON |
| 通知 新規 D / リマインダ E | D = 新規 pending 数（A）、E = 月曜なら notified_at != null の件数、それ以外は 0 |

ルール:
- 「【XXX】N件」セクションは N=0 でも `【XXX】0件` と書く（あるいは省略）。任意で良い
- 各 link 1 つにつき 1 つの bullet。候補は最高信頼度の 1 件のみ表示
- 月曜リマインダは月曜のみ。`date +%u` が `1` のとき表示
- `queue.json` の中身そのものは絶対に貼らない（要約のみ）
- 実行サマリは**冒頭に必ず置く**。可視化が目的なので省略しない

絶対禁止：
- `Verification complete: ...` のような verification ログを最終応答に出す
- `Now I'll generate the Discord report` のような前置きを書く
- 「mark-notified を実行しました」など内部処理の説明を最終応答に含める

これらは内部 reasoning として行うのは構わないが、**最終応答（=Discord に配信される文）には含めない**。

## Pitfalls

### スコープ外のものを作らない

- **v1 では Discord 通知のみ**。02_people/<人物>.md や 01_projects/<slug>/<slug>.md を**自分で作成しない**
- ユーザーが手動で対応するので、推奨アクションを明示するに留める

### 信頼度補正の慎みやさ

- LLM の補正は **±0.10 まで**。score-based の判定を覆さない
- 補正の理由は `reasons` に追記（例: `"llm_context: 同会議に品川武利"`）

### Discord ノイズを避ける

- **月曜リマインダ以外は既存 pending を出さない**
- リンクごとに候補は **上位 1 件のみ**を出力（`suggest_candidates --top 1`）
- queue.json の中身そのものは絶対に貼らない

### 重複・統合の扱い

- 同じ link が複数ファイルに出現 → `update_queue` 内で appearances 統合（実装済み）
- 既に resolved な link が再びスキャンに登場 → `update_queue` 内で skip（実装済み）
- candidates は毎回最新スキャン結果で上書き

### 月曜判定

- `date +%u` で 1=月曜。これを Agent が確認する
- Hermes cron は毎日同じ時刻に動くので、月曜判定は Agent 側で行う必要がある

### 候補なしの取り扱い

- 候補が 0 件 = 「新規エンティティ提案」として扱う
- excluded.txt に該当する場合は scan で既に除外されているので通知に来ない（再確認不要）

### kind=unknown の扱い

- LLM が文脈を読んで person/project/concept に再分類できる場合は補正可
- 再分類しても既存エンティティ照合・候補推測は行う
- 不明のまま → 「その他/判定不能」として通知し、ユーザーに excluded.txt 追加 or 新規作成を委ねる

### concept 判定の弱さ（語尾依存）

- `kind == concept` は弱パターン (`戦略|方法論|設計|思考|モデル|フレームワーク|理論|哲学|主義|手法|アプローチ` の suffix) に依存しており確度は中程度
- field context (`concept:`, `topic:`, `frame:` 等) で出現する場合は Layer 2 で確実に concept 判定される
- suffix リストに該当しない概念ノート（例: 「資産形成」「ナレッジ統合」）は `unknown` になる可能性あり。LLM が文脈で `concept` に補正してよい
- suffix の誤検出（人物名に「論」を含む等）を避けるため、初版では単漢字 suffix (`論|学`) は除外している

## Verification

各実行の自己確認（**内部 reasoning として実施。最終応答には含めない**）：

1. **queue.json の整合性**:
   `python3 update_queue.py --action stats`
   pending 件数が scan_unresolved と矛盾しないこと（resolved/dismissed 分は減算）

2. **通知対象 0 件なら [SILENT]**:
   新規 pending が 0 件 かつ 月曜でない → `[SILENT] no unresolved links to notify` のみ最終応答

3. **mark-notified の反映**:
   通知した ID が queue.json で `notified_at` 入りに更新されている

4. **副作用なし**:
   v1 では vault 配下のファイルを編集・作成しない（queue.json 以外）

5. **最終応答のフォーマット**:
   ステップ 7 のフォーマットに正確に従っているか（verification ログや前置き混入なし）
