#!/usr/bin/env python3
"""
detect_id_collisions.py: vault/05_tasks/ 内のタスク ID 衝突を検出・自動修復する。

ファイル名と frontmatter の id: フィールドを両方スキャンし、同一 ID が複数ファイルに
割り当てられている場合に「新しい側」へ suffix ([a-z]) を付与してリネームする。
リネームには git mv を使い、history を保全する。
関連する wikilink を vault 全体で書き換える。

Usage:
  python3 detect_id_collisions.py [--dry-run] [--pretty] [--scan-paths PATH1,PATH2,...]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# 共通通知ライブラリを import するため skills/ を sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _common.notify import notify  # noqa: E402

# ── パス定数 ──────────────────────────────────────────────────────────────────
# VAULT_PATH 環境変数で上書き可。デフォルトはリポジトリ直下の vault/
VAULT_DIR = Path(os.environ.get('VAULT_PATH', Path(__file__).resolve().parents[3] / 'vault')).expanduser().resolve()
TASKS_DIR = VAULT_DIR / "05_tasks"
ARCHIVE_DIR = TASKS_DIR / "archive"

# デフォルト走査パターン
DEFAULT_SCAN_GLOBS = [
    TASKS_DIR / "T*.md",
    ARCHIVE_DIR / "**/T*.md",
]

# frontmatter の id フィールドにマッチする regex
# 例: "id: T0115" "id: T0115a"
_FRONTMATTER_ID_RE = re.compile(r"^id:\s+(T\d{4}[a-z]?)\s*$", re.MULTILINE)

# ファイル名から ID を抽出する regex（例: T0115-foo.md → T0115）
_FILENAME_ID_RE = re.compile(r"^(T\d{4}[a-z]?)-")

# 既に suffix 付きの ID（T0115a 等）は処理スキップ対象
_SUFFIX_ID_RE = re.compile(r"^T\d{4}[a-z]-")


# ── frontmatter ────────────────────────────────────────────────────────────────

def extract_frontmatter_id(content: str) -> Optional[str]:
    """frontmatter の id: フィールドの値を返す。なければ None。"""
    m = _FRONTMATTER_ID_RE.search(content)
    return m.group(1) if m else None


def extract_filename_id(filename: str) -> Optional[str]:
    """ファイル名から ID 部分（例: T0115）を抽出する。"""
    m = _FILENAME_ID_RE.match(filename)
    return m.group(1) if m else None


def is_already_resolved(filepath: Path) -> bool:
    """ファイル名と frontmatter の両方が suffix 付きで一致するなら修復済み。

    ファイル名は suffix 付きでも frontmatter ID が古い値のままの場合は
    「未修復」として扱い、warning を出す。
    """
    filename = filepath.name
    if not _SUFFIX_ID_RE.match(filename):
        return False
    # frontmatter も確認
    try:
        content = filepath.read_text(encoding="utf-8")
        fm_id = extract_frontmatter_id(content)
        fn_id = extract_filename_id(filename)
        if fm_id and fn_id and fm_id != fn_id:
            print(
                f"[WARN] frontmatter ID 不一致（ファイル名={fn_id}, frontmatter={fm_id}）: {filepath}",
                file=sys.stderr,
            )
            return False  # 不一致は「未修復」として扱う
        return True
    except OSError:
        return False


# ── path traversal 対策 ───────────────────────────────────────────────────────

def _is_within_vault(path: Path) -> bool:
    """path が VAULT_DIR 配下にあるか確認（symlink 解決後）。"""
    try:
        resolved = path.resolve()
        vault_resolved = VAULT_DIR.resolve()
        # Path.is_relative_to は Python 3.9+。後方互換のため startswith でチェック
        return str(resolved).startswith(str(vault_resolved) + os.sep) or str(resolved) == str(vault_resolved)
    except (OSError, RuntimeError):
        return False


# ── ファイル収集 ────────────────────────────────────────────────────────────────

def collect_task_files(scan_paths: Optional[list[str]] = None) -> list[Path]:
    """走査対象ファイルの一覧を返す。"""
    if scan_paths:
        files: list[Path] = []
        for p in scan_paths:
            path = Path(p).expanduser()
            if path.is_file():
                if not _is_within_vault(path):
                    print(f"[WARN] VAULT_DIR 外のため除外: {path}", file=sys.stderr)
                    continue
                files.append(path)
            elif path.is_dir():
                for candidate in sorted(path.rglob("T*.md")):
                    if not _is_within_vault(candidate):
                        print(f"[WARN] VAULT_DIR 外のため除外: {candidate}", file=sys.stderr)
                        continue
                    files.append(candidate)
            else:
                # glob パターンとして解釈
                parent = path.parent
                pattern = path.name
                if parent.exists():
                    for candidate in sorted(parent.glob(pattern)):
                        if not _is_within_vault(candidate):
                            print(f"[WARN] VAULT_DIR 外のため除外: {candidate}", file=sys.stderr)
                            continue
                        files.append(candidate)
        return sorted(set(files))

    files = []
    # デフォルト: 05_tasks/T*.md
    if TASKS_DIR.exists():
        files.extend(sorted(TASKS_DIR.glob("T*.md")))
    # デフォルト: 05_tasks/archive/**/T*.md（存在しない場合は 0 件）
    if ARCHIVE_DIR.exists():
        files.extend(sorted(ARCHIVE_DIR.rglob("T*.md")))
    return files


# ── ID 収集 ────────────────────────────────────────────────────────────────────

def collect_id_map(files: list[Path]) -> dict[str, list[Path]]:
    """ID -> [Path, ...] のマッピングを返す（重複があれば複数エントリ）。"""
    id_map: dict[str, list[Path]] = {}
    for path in files:
        # ファイル名から ID 取得
        fid = extract_filename_id(path.name)
        if not fid:
            continue
        # frontmatter からも確認（不一致は警告のみで、ファイル名を正とする）
        try:
            content = path.read_text(encoding="utf-8")
            fm_id = extract_frontmatter_id(content)
        except OSError:
            fm_id = None

        # ファイル名 ID を採用（frontmatter が異なる場合も含め、ファイル名を権威とする）
        if fid not in id_map:
            id_map[fid] = []
        id_map[fid].append(path)

        # frontmatter ID がファイル名 ID と異なる場合も衝突対象に追加
        if fm_id and fm_id != fid:
            if fm_id not in id_map:
                id_map[fm_id] = []
            # frontmatter 上の衝突として記録（同じパスを追加しない）
            if path not in id_map[fm_id]:
                id_map[fm_id].append(path)

    return id_map


# ── git author date ────────────────────────────────────────────────────────────

def get_git_author_date(path: Path) -> str:
    """path のファイルが最初に git に追加された author date (ISO 8601) を返す。

    取得できない場合は空文字列。
    """
    rel = path.relative_to(VAULT_DIR)
    result = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%aI", "--", str(rel)],
        cwd=VAULT_DIR,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    return result.stdout.strip().splitlines()[0].strip()


# ── suffix 割り当て ────────────────────────────────────────────────────────────

def assign_suffix(base_id: str, existing_ids: set[str]) -> str:
    """base_id（例: T0115）に対して未使用の最小 suffix を返す。

    T0115a, T0115b, ... T0115z の順に探す。
    使い切った場合は RuntimeError。
    """
    for ch in "abcdefghijklmnopqrstuvwxyz":
        candidate = f"{base_id}{ch}"
        if candidate not in existing_ids:
            return candidate
    raise RuntimeError(
        f"T####z まで使い切りました（base={base_id}）。人間による手動対応が必要です。"
    )


# ── frontmatter id 書き換え ────────────────────────────────────────────────────

def rewrite_frontmatter_id(content: str, new_id: str) -> str:
    """frontmatter の id: フィールドを new_id に書き換えた content を返す。

    YAML パーサを使わず正規表現で surgical 置換（他フィールドを保全）。
    """
    return _FRONTMATTER_ID_RE.sub(f"id: {new_id}", content, count=1)


# ── wikilink 書き換え ─────────────────────────────────────────────────────────

def build_wikilink_pattern(old_stem: str) -> re.Pattern:
    """old_stem（ファイル名ステム全体）の wikilink にマッチする regex パターンを返す。

    例: old_stem="T0115-bar-slug" のとき
        [[T0115-bar-slug]], [[T0115-bar-slug#heading]], [[T0115-bar-slug|display]] にマッチ。
        [[T0115-foo-slug]] にはマッチしない。

    re.escape() でハイフン等を安全にエスケープする。
    末尾の `([#|][^\\]]*)?` は heading / display name をキャプチャする optional グループ。
    """
    escaped = re.escape(old_stem)
    pattern = r"\[\[" + escaped + r"([#|][^\]]*)?\]\]"
    return re.compile(pattern)


def rewrite_wikilinks_in_content(content: str, old_stem: str, new_stem: str) -> tuple[str, int]:
    """content 内の old_stem wikilink を new_stem に書き換える。

    [[old_stem]], [[old_stem#heading]], [[old_stem|display]] のみ置換対象。
    同じ ID でも別 stem を持つリンクは維持される。

    Returns:
        (新しい content, 置換件数)
    """
    pattern = build_wikilink_pattern(old_stem)

    count = 0

    def replacer(m: re.Match) -> str:
        nonlocal count
        count += 1
        suffix = m.group(1) or ""
        return f"[[{new_stem}{suffix}]]"

    new_content = pattern.sub(replacer, content)
    return new_content, count


def rewrite_wikilinks_vault_wide(
    old_stem: str,
    new_stem: str,
    dry_run: bool,
) -> tuple[int, list[str]]:
    """vault 全体の .md ファイルで wikilink を old_stem → new_stem に書き換える。

    old_stem はリネーム対象ファイルのステム全体（例: "T0115-bar-slug"）。
    同じ base ID を持つ別ファイル（例: "T0115-foo-slug"）への wikilink は変更しない。

    Returns:
        (総置換件数, 変更されたファイルパスのリスト)
    """
    total_updates = 0
    touched_files: list[str] = []

    if not VAULT_DIR.exists():
        return 0, []

    for md_path in sorted(VAULT_DIR.rglob("*.md")):
        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError:
            continue

        new_content, count = rewrite_wikilinks_in_content(content, old_stem, new_stem)
        if count > 0:
            total_updates += count
            rel_path = str(md_path.relative_to(Path.home() / "studio"))
            touched_files.append(f"studio/{rel_path}" if not rel_path.startswith("studio") else rel_path)
            if not dry_run:
                try:
                    md_path.write_text(new_content, encoding="utf-8")
                except OSError as e:
                    raise OSError(f"wikilink 書換失敗: {md_path}: {e}") from e

    return total_updates, touched_files


# ── git mv ────────────────────────────────────────────────────────────────────

def git_mv(old_path: Path, new_path: Path) -> None:
    """git mv を使ってファイルをリネームする。失敗時は RuntimeError。"""
    old_rel = str(old_path.relative_to(VAULT_DIR))
    new_rel = str(new_path.relative_to(VAULT_DIR))
    result = subprocess.run(
        ["git", "mv", old_rel, new_rel],
        cwd=VAULT_DIR,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git mv 失敗: {old_rel} → {new_rel}\n"
            f"stderr: {result.stderr.strip()}"
        )


# ── 通知 ───────────────────────────────────────────────────────────────────────

def send_collision_notification(
    collisions_detected: int,
    collisions_resolved: int,
    total_wikilink_updates: int,
    is_error: bool = False,
    error_message: str = "",
) -> None:
    """通知 sink (env: NOTIFICATION_SINK) にメッセージを送る。失敗してもエラーにしない。"""
    if is_error:
        message = (
            f"ID 衝突修復中にエラーが発生しました\n"
            f"- 検出: {collisions_detected} 件\n"
            f"- エラー: {error_message}\n"
            f"- 詳細: vault-sync ログを参照"
        )
    else:
        message = (
            f"ID 衝突を自動修復しました\n"
            f"- 検出: {collisions_detected} 件\n"
            f"- 解決: {collisions_resolved} 件\n"
            f"- 影響 wikilink: {total_wikilink_updates} 箇所\n"
            f"- 詳細: vault-sync ログを参照"
        )
    notify(message)


# ── 衝突検出・修復 ────────────────────────────────────────────────────────────

def detect_and_resolve(
    files: list[Path],
    dry_run: bool,
    verbose: bool = False,
) -> dict:
    """衝突を検出して修復し、レポート dict を返す。"""
    id_map = collect_id_map(files)

    # 全既存 ID セット（suffix 割り当てで使用）
    all_ids: set[str] = set(id_map.keys())

    collisions_detected = 0
    collisions_resolved = 0
    skipped_already_resolved = 0
    renames: list[dict] = []
    failures: list[dict] = []

    # 重複 ID のみ処理
    duplicate_ids = {k: v for k, v in id_map.items() if len(v) > 1}

    for base_id, paths in sorted(duplicate_ids.items()):
        collisions_detected += 1

        # suffix 付き ID は既解決済みとしてスキップ
        already_resolved = [p for p in paths if is_already_resolved(p)]
        if already_resolved:
            skipped_already_resolved += 1
            if verbose:
                print(
                    f"[SKIP] {base_id}: 既に解決済み suffix ファイルが存在 "
                    f"({[p.name for p in already_resolved]})",
                    file=sys.stderr,
                )
            continue

        # author date でソートして古い側・新しい側を判定
        dated: list[tuple[str, Path]] = []
        for path in paths:
            date_str = get_git_author_date(path)
            dated.append((date_str, path))

        # 日付昇順（author date が小さい = 古い = 維持側）
        dated.sort(key=lambda x: x[0])
        # 最も古い 1 件を「維持」（インデックス 0）、それ以外を「新しい側（suffix 付与対象）」とする
        to_rename_list = [p for _, p in dated[1:]]

        for to_rename in to_rename_list:
            try:
                new_id = assign_suffix(base_id, all_ids)
            except RuntimeError as e:
                failures.append({
                    "base_id": base_id,
                    "path": str(to_rename.relative_to(Path.home() / "studio")),
                    "error": str(e),
                })
                send_collision_notification(
                    collisions_detected=collisions_detected,
                    collisions_resolved=collisions_resolved,
                    total_wikilink_updates=0,
                    is_error=True,
                    error_message=str(e),
                )
                continue

            all_ids.add(new_id)

            # 新しいファイルパスを構築
            old_name = to_rename.name
            # T0115-slug.md → T0115a-slug.md
            new_name = re.sub(r"^T\d{4}", new_id, old_name, count=1)
            new_path = to_rename.parent / new_name

            # ファイル名ステム単位で wikilink を特定（同 base_id の別ファイルを巻き込まない）
            old_stem = to_rename.stem  # 例: "T0115-bar-slug"
            new_stem = re.sub(r"^T\d{4}[a-z]?", new_id, old_stem, count=1)  # 例: "T0115a-bar-slug"

            # wikilink 書換を先に試みる（dry_run 対応）
            try:
                wikilink_count, touched_files = rewrite_wikilinks_vault_wide(
                    old_stem=old_stem,
                    new_stem=new_stem,
                    dry_run=dry_run,
                )
            except OSError as e:
                failures.append({
                    "base_id": base_id,
                    "old_path": str(to_rename.relative_to(Path.home() / "studio")),
                    "error": f"wikilink 書換失敗: {e}",
                })
                send_collision_notification(
                    collisions_detected=collisions_detected,
                    collisions_resolved=collisions_resolved,
                    total_wikilink_updates=0,
                    is_error=True,
                    error_message=str(e),
                )
                continue

            # ファイル自体の frontmatter id を書き換え
            if not dry_run:
                try:
                    content = to_rename.read_text(encoding="utf-8")
                    new_content = rewrite_frontmatter_id(content, new_id)
                    to_rename.write_text(new_content, encoding="utf-8")
                except OSError as e:
                    failures.append({
                        "base_id": base_id,
                        "old_path": str(to_rename.relative_to(Path.home() / "studio")),
                        "error": f"frontmatter 書換失敗: {e}",
                    })
                    continue

                # git mv でリネーム
                try:
                    git_mv(to_rename, new_path)
                except RuntimeError as e:
                    failures.append({
                        "base_id": base_id,
                        "old_path": str(to_rename.relative_to(Path.home() / "studio")),
                        "new_path": str(new_path.relative_to(Path.home() / "studio")),
                        "error": str(e),
                    })
                    send_collision_notification(
                        collisions_detected=collisions_detected,
                        collisions_resolved=collisions_resolved,
                        total_wikilink_updates=0,
                        is_error=True,
                        error_message=str(e),
                    )
                    continue

            collisions_resolved += 1
            renames.append({
                "old_id": base_id,
                "new_id": new_id,
                "old_path": str(to_rename.relative_to(Path.home() / "studio")),
                "new_path": str(new_path.relative_to(Path.home() / "studio")),
                "wikilink_updates": wikilink_count,
                "wikilink_files_touched": touched_files,
            })

    return {
        "collisions_detected": collisions_detected,
        "collisions_resolved": collisions_resolved,
        "skipped_already_resolved": skipped_already_resolved,
        "renames": renames,
        "failures": failures,
    }


# ── pretty 出力 ────────────────────────────────────────────────────────────────

def format_pretty(report: dict, dry_run: bool) -> str:
    """人間可読なレポートを返す。"""
    lines: list[str] = []
    prefix = "[DRY-RUN] " if dry_run else ""

    lines.append(f"{prefix}=== detect_id_collisions レポート ===")
    lines.append(f"  衝突検出: {report['collisions_detected']} 件")
    lines.append(f"  解決済み: {report['collisions_resolved']} 件")
    lines.append(f"  スキップ（既解決）: {report['skipped_already_resolved']} 件")

    if report["renames"]:
        lines.append("")
        lines.append("  リネーム一覧:")
        for r in report["renames"]:
            lines.append(f"    {r['old_id']} → {r['new_id']}")
            lines.append(f"      {r['old_path']}")
            lines.append(f"      → {r['new_path']}")
            lines.append(f"      wikilink 更新: {r['wikilink_updates']} 箇所 ({len(r['wikilink_files_touched'])} ファイル)")

    if report["failures"]:
        lines.append("")
        lines.append("  エラー:")
        for f in report["failures"]:
            lines.append(f"    - {f.get('base_id', '?')}: {f['error']}")

    return "\n".join(lines)


# ── メインエントリポイント ─────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="vault/05_tasks/ 内のタスク ID 衝突を検出・自動修復する"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="リネーム・書換を実行せず、レポートのみ出力",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="JSON ではなく人間可読な出力",
    )
    parser.add_argument(
        "--scan-paths",
        type=str,
        default="",
        help="カンマ区切りの走査対象パス（省略時は既定パスを使用）",
    )
    args = parser.parse_args()

    # 走査パスの解決
    scan_paths: Optional[list[str]] = None
    if args.scan_paths:
        scan_paths = [p.strip() for p in args.scan_paths.split(",") if p.strip()]

    # ファイル収集
    files = collect_task_files(scan_paths)

    # 衝突検出・修復
    report = detect_and_resolve(files, dry_run=args.dry_run)

    # Discord 通知（dry_run 時は送らない）
    if not args.dry_run and report["collisions_detected"] > 0:
        total_wikilinks = sum(r["wikilink_updates"] for r in report["renames"])
        send_collision_notification(
            collisions_detected=report["collisions_detected"],
            collisions_resolved=report["collisions_resolved"],
            total_wikilink_updates=total_wikilinks,
        )

    # 出力
    if args.pretty:
        print(format_pretty(report, dry_run=args.dry_run))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
