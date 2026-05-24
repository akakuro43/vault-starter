"""
Transcript Importer: Google Drive の transcript フォルダ → vault/00_inbox/meeting_transcripts/ に取り込む

使い方:
  python3 fetch_transcripts.py            # 通常運用（新規ファイルのみ取り込み）
  python3 fetch_transcripts.py --reseed   # 既存ファイルを取り込み済みとして記録のみ
  python3 fetch_transcripts.py --all      # 全ファイル強制再取り込み（リカバリ用）

初回実行時（transcripts_imported.json が存在しない）は自動で seed モード。
既存ファイルを記録だけして本文は取り込まない。以降の実行で新規ファイルのみ取り込む。

環境変数:
  VAULT_PATH                       vault のパス (デフォルト: リポジトリ直下の vault/)
  GOOGLE_DRIVE_CREDENTIALS_PATH    OAuth credentials.json のパス (デフォルト: ./credentials/google-drive.json)
  GOOGLE_DRIVE_TOKEN_PATH          token.json の保存先 (デフォルト: ./credentials/token.json)
  GOOGLE_DRIVE_TRANSCRIPT_FOLDER   Drive 上のフォルダ名 (デフォルト: MTG_Transcripts)
  GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID  フォルダ ID 直接指定 (任意。指定時は name 検索より優先)
"""
import os
import re
import sys
import json
import argparse
import html2text
from datetime import datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── パス設定 ──────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]  # vault-starter/
BASE_DIR  = Path(__file__).resolve().parent.parent  # skills/mtg-importer/

VAULT_DIR = Path(os.environ.get('VAULT_PATH', REPO_ROOT / 'vault')).expanduser().resolve()
INBOX_DIR = VAULT_DIR / '00_inbox' / 'meeting_transcripts'

CREDENTIALS_FILE = Path(os.environ.get(
    'GOOGLE_DRIVE_CREDENTIALS_PATH',
    REPO_ROOT / 'credentials' / 'google-drive.json'
)).expanduser()
TOKEN_FILE = Path(os.environ.get(
    'GOOGLE_DRIVE_TOKEN_PATH',
    REPO_ROOT / 'credentials' / 'token.json'
)).expanduser()

IMPORTED_LOG = BASE_DIR / 'transcripts_imported.json'

DRIVE_FOLDER_NAME = os.environ.get('GOOGLE_DRIVE_TRANSCRIPT_FOLDER', 'MTG_Transcripts')
DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID', '').strip() or None

# TRANSCRIPT_YY.MM.DD_タイトル(_owner@domain)
# email 部分は ASCII のみで限定して、日本語タイトルとの境界を明確にする
FILENAME_PATTERN = re.compile(
    r'^TRANSCRIPT_(\d{2})\.(\d{2})\.(\d{2})_(.+?)(?:_([a-zA-Z0-9.+-]+@[a-zA-Z0-9.-]+))?$'
)

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


# ── ファイル名パース ──────────────────────────────────────────
def parse_filename(name: str):
    """
    TRANSCRIPT_26.05.01_定例会_your.name@example.com
      → {date: 2026-05-01, title: 定例会, owner: your.name@example.com}
    TRANSCRIPT_26.05.01_社内MTG_すり合わせ_your.name@example.com
      → {date: 2026-05-01, title: 社内MTG_すり合わせ, owner: your.name@example.com}
    """
    m = FILENAME_PATTERN.match(name.strip())
    if not m:
        return None
    yy, mm, dd, title, owner = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    return {
        'date': f'20{yy}-{mm}-{dd}',
        'title': title,
        'owner': owner or '',
    }


# ── Google Drive 認証 ─────────────────────────────────────────
def get_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(f'ERROR: credentials file not found: {CREDENTIALS_FILE}', file=sys.stderr)
                print(f'  set GOOGLE_DRIVE_CREDENTIALS_PATH or place credentials at {CREDENTIALS_FILE}', file=sys.stderr)
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TOKEN_FILE.open('w') as f:
            f.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)


# ── フォルダ内ファイル一覧取得 ────────────────────────────────
def list_files_in_folder(service, folder_id: str) -> list:
    files = []
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false",
            fields='nextPageToken, files(id, name, modifiedTime)',
            pageToken=page_token
        ).execute()
        files.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return files


# ── Google Doc を HTML でエクスポート → Markdown に変換 ──────
def export_doc_as_markdown(service, file_id: str) -> str:
    html = service.files().export(
        fileId=file_id,
        mimeType='text/html'
    ).execute()
    if isinstance(html, bytes):
        html = html.decode('utf-8')

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0
    h.protect_links = True
    h.wrap_links = False
    return h.handle(html)


# ── Markdown ファイルを生成 ───────────────────────────────────
def build_markdown(parsed: dict, content: str, drive_id: str, drive_filename: str) -> str:
    today = datetime.now().strftime('%Y-%m-%d')
    owner_line = f'\nowner: {parsed["owner"]}' if parsed['owner'] else ''
    frontmatter = f"""---
date: {parsed['date']}
title: "{parsed['title']}"
type: transcript
source: google-drive
drive_id: {drive_id}
drive_filename: "{drive_filename}"{owner_line}
imported: {today}
---

"""
    return frontmatter + content.strip() + '\n'


def safe_filename(title: str) -> str:
    """ファイル名に使えない文字を除去"""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title)[:80]


# ── インポート済みログ ─────────────────────────────────────────
def load_imported_log() -> set:
    if IMPORTED_LOG.exists():
        with IMPORTED_LOG.open() as f:
            return set(json.load(f))
    return set()


def save_imported_log(imported: set):
    with IMPORTED_LOG.open('w') as f:
        json.dump(list(imported), f, ensure_ascii=False, indent=2)


# ── メイン ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true',
                        help='既存記録を無視して全ファイル再取り込み')
    parser.add_argument('--reseed', action='store_true',
                        help='既存ファイルを取り込み済みとして記録のみ（本文は取り込まない）')
    args = parser.parse_args()

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    service = get_service()

    # 対象フォルダ ID を解決
    if DRIVE_FOLDER_ID:
        folder_id = DRIVE_FOLDER_ID
        print(f'対象フォルダ (ID 指定): {folder_id}')
    else:
        resp = service.files().list(
            q=f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields='files(id, name)'
        ).execute()
        folders = resp.get('files', [])
        if not folders:
            print(f'ERROR: {DRIVE_FOLDER_NAME} フォルダが見つかりません')
            sys.exit(1)
        folder_id = folders[0]['id']
        print(f'{DRIVE_FOLDER_NAME} フォルダ: {folder_id}')

    # ★ サブフォルダは走査しない（直下のみ対象）
    all_files = list_files_in_folder(service, folder_id)
    print(f'対象ファイル数: {len(all_files)}')

    is_first_run = not IMPORTED_LOG.exists()

    if args.all:
        seed_mode = False
        imported_ids = set()
        print('モード: 全件再取り込み（--all）')
    elif args.reseed or is_first_run:
        seed_mode = True
        imported_ids = load_imported_log()
        reason = '初回実行' if is_first_run else '--reseed'
        print(f'モード: シード（{reason}） — 既存ファイルを記録のみ。本文は取り込まない')
    else:
        seed_mode = False
        imported_ids = load_imported_log()
        print('モード: 通常運用（新規ファイルのみ取り込み）')

    new_count   = 0
    skip_count  = 0
    error_count = 0
    seed_count  = 0

    for f in all_files:
        file_id = f['id']
        name    = f['name']

        if file_id in imported_ids:
            skip_count += 1
            continue

        if seed_mode:
            imported_ids.add(file_id)
            seed_count += 1
            print(f'  SEED {name}')
            continue

        parsed = parse_filename(name)
        if not parsed:
            print(f'  SKIP (パース不可): {name}')
            skip_count += 1
            continue

        try:
            content = export_doc_as_markdown(service, file_id)
        except Exception as e:
            print(f'  ERROR (エクスポート失敗): {name} — {e}')
            error_count += 1
            continue

        md = build_markdown(parsed, content, file_id, name)

        safe_title = safe_filename(parsed['title'])
        out_filename = f"{parsed['date']}_{safe_title}.md"
        out_path = INBOX_DIR / out_filename

        with out_path.open('w', encoding='utf-8') as out:
            out.write(md)

        imported_ids.add(file_id)
        new_count += 1
        print(f'  OK {out_filename}')

    save_imported_log(imported_ids)

    if seed_mode:
        print(f'\n完了 — シード記録: {seed_count}件 / スキップ: {skip_count}件')
    else:
        print(f'\n完了 — 新規: {new_count}件 / スキップ: {skip_count}件 / エラー: {error_count}件')


if __name__ == '__main__':
    main()
