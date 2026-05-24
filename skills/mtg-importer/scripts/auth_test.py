"""
Google Drive 認証テスト
初回実行時にブラウザが開くので Google アカウントでログインしてください。
token.json が生成されれば成功。

環境変数:
  GOOGLE_DRIVE_CREDENTIALS_PATH    OAuth credentials.json のパス
  GOOGLE_DRIVE_TOKEN_PATH          token.json の保存先
  GOOGLE_DRIVE_TRANSCRIPT_FOLDER   Drive 上のフォルダ名 (デフォルト: MTG_Transcripts)
"""
import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

REPO_ROOT = Path(__file__).resolve().parents[3]
CREDENTIALS_FILE = Path(os.environ.get(
    'GOOGLE_DRIVE_CREDENTIALS_PATH',
    REPO_ROOT / 'credentials' / 'google-drive.json'
)).expanduser()
TOKEN_FILE = Path(os.environ.get(
    'GOOGLE_DRIVE_TOKEN_PATH',
    REPO_ROOT / 'credentials' / 'token.json'
)).expanduser()
FOLDER_NAME = os.environ.get('GOOGLE_DRIVE_TRANSCRIPT_FOLDER', 'MTG_Transcripts')


def get_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TOKEN_FILE.open('w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)


if __name__ == '__main__':
    service = get_service()
    results = service.files().list(
        q=f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder'",
        fields="files(id, name)"
    ).execute()
    folders = results.get('files', [])
    if folders:
        print('OK 認証成功')
        print(f"OK {FOLDER_NAME} フォルダ発見: id={folders[0]['id']}")
    else:
        print(f'OK 認証成功（{FOLDER_NAME} フォルダは見つかりませんでした）')
