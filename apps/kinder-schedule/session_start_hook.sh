#!/bin/bash
# SessionStart 훅: 1) 지난 날짜 항목 취소선 자동 갱신 2) 하루 첫 세션에만 e알리미 확인 리마인드
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

python3 apps/kinder-schedule/mark_past_due.py >/dev/null 2>&1 || true

STAMP_FILE=".claude/.last-kinder-check"
TODAY="$(date +%Y-%m-%d)"
LAST=""
[ -f "$STAMP_FILE" ] && LAST="$(cat "$STAMP_FILE")"

if [ "$LAST" != "$TODAY" ]; then
  echo "$TODAY" > "$STAMP_FILE"
  cat <<JSON
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "오늘 첫 세션입니다. 사용자에게 e알리미(https://www.ealimi.com)에 새 가정통신문·식단표가 있는지 확인해드릴지 먼저 물어보세요. 원한다고 하면 claude-in-chrome으로 로그인된 세션에 들어가 kinder-pdf 스킬 절차대로 처리하세요."}}
JSON
fi
