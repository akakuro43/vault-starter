#!/bin/bash
# pipeline.sh
# トランスクリプト取り込みパイプライン（cron で定期実行を想定、例: 毎時:05）

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOG_FILE="${MTG_IMPORTER_LOG:-$REPO_ROOT/logs/mtg-importer.log}"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p "$(dirname "$LOG_FILE")"

echo "[$TIMESTAMP] ===== pipeline start =====" >> "$LOG_FILE"

# .env を読み込む（あれば）
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

echo "[$TIMESTAMP] [1/1] fetch_transcripts.py" >> "$LOG_FILE"
python3 "$SCRIPT_DIR/fetch_transcripts.py" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "[$TIMESTAMP] ===== pipeline end (exit: $EXIT_CODE) =====" >> "$LOG_FILE"
exit $EXIT_CODE
