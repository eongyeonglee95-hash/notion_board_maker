#!/usr/bin/env python3
"""
노션의 유치원 일정 · 제출·준비물 을 확인해서 D-7/D-3/D-1 에 슬랙으로 알린다.

의존성 없음(표준 라이브러리만 사용). notion.py 를 옆에서 불러 쓴다.

사용법:
  python3 apps/kinder-schedule/notify.py --dry-run              # 발송 없이 메시지만 출력
  python3 apps/kinder-schedule/notify.py --dry-run --date 2026-09-12  # 특정 날짜인 척
  python3 apps/kinder-schedule/notify.py                        # 실제 발송

.env 에 SLACK_WEBHOOK_URL 이 있어야 실제 발송이 된다 (--dry-run 은 없어도 된다).
"""

import argparse
import datetime
import importlib.util
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
NOTION_PY = os.path.join(
    REPO, ".claude", "skills", "notion-organizer", "scripts", "notion.py"
)
TARGETS_JSON = os.path.join(REPO, "notion_targets.json")

D_DAYS = (7, 3, 1)  # 이 날짜에만 발송한다


def load_notion():
    if not os.path.exists(NOTION_PY):
        sys.exit(f"notion.py 를 찾을 수 없습니다: {NOTION_PY}")
    spec = importlib.util.spec_from_file_location("notion_client", NOTION_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_targets():
    with open(TARGETS_JSON, encoding="utf-8") as f:
        return json.load(f)


def load_slack_webhook():
    """환경변수 또는 .env 에서 SLACK_WEBHOOK_URL 을 읽는다. notion.py 의 load_token 과 같은 방식."""
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if url:
        return url.strip().strip('"').strip("'")

    env_path = os.path.join(REPO, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == "SLACK_WEBHOOK_URL":
                    return value.strip().strip('"').strip("'")
    return None


def query_all(mod, data_source_id):
    """데이터소스의 모든 행을 원본 그대로(단순화 없이) 가져온다."""
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = mod.request("POST", f"/data_sources/{data_source_id}/query", body)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


def prop_text(row, name):
    prop = row.get("properties", {}).get(name, {})
    ptype = prop.get("type")
    if ptype == "title":
        return mod_plain(prop.get("title"))
    if ptype == "rich_text":
        return mod_plain(prop.get("rich_text"))
    return ""


def mod_plain(rich):
    return "".join(r.get("plain_text", "") for r in (rich or []))


def prop_date_start(row, name):
    prop = row.get("properties", {}).get(name, {})
    d = prop.get("date")
    if not d:
        return None
    start = d.get("start")
    if not start:
        return None
    return datetime.date.fromisoformat(start[:10])


def prop_checkbox(row, name):
    return bool(row.get("properties", {}).get(name, {}).get("checkbox"))


def prop_select(row, name):
    sel = row.get("properties", {}).get(name, {}).get("select")
    return sel.get("name") if sel else None


def weekday_kr(d):
    return "월화수목금토일"[d.weekday()]


def collect(mod, targets, today):
    """D-7/D-3/D-1 에 해당하는 항목만 골라낸다."""
    vacation_items = []
    submission_items = []

    ds_schedule = targets["유치원 일정"]["data_source_id"]
    for row in query_all(mod, ds_schedule):
        if not prop_checkbox(row, "휴가필요"):
            continue
        d = prop_date_start(row, "날짜")
        if not d:
            continue
        dday = (d - today).days
        if dday not in D_DAYS:
            continue
        vacation_items.append({
            "이름": prop_text(row, "일정명"),
            "날짜": d,
            "담당": prop_select(row, "담당") or "미정",
            "dday": dday,
        })

    ds_submission = targets["제출·준비물"]["data_source_id"]
    for row in query_all(mod, ds_submission):
        if prop_checkbox(row, "완료"):
            continue
        d = prop_date_start(row, "마감일")
        if not d:
            continue
        dday = (d - today).days
        if dday not in D_DAYS:
            continue
        submission_items.append({
            "이름": prop_text(row, "항목명"),
            "날짜": d,
            "담당": prop_select(row, "담당") or "미정",
            "dday": dday,
        })

    vacation_items.sort(key=lambda x: x["dday"])
    submission_items.sort(key=lambda x: x["dday"])
    return vacation_items, submission_items


def format_item(item):
    d = item["날짜"]
    date_str = f"{d.month}/{d.day}({weekday_kr(d)})"
    담당 = item["담당"]
    담당_str = f"담당: {담당} ❗" if 담당 == "미정" else f"담당: {담당}"
    return f"  {date_str} {item['이름']}  — D-{item['dday']} · {담당_str}"


def build_message(vacation_items, submission_items):
    if not vacation_items and not submission_items:
        return None

    lines = ["🏫 유치원 알림", ""]
    if vacation_items:
        lines.append("⚠️ 휴가 필요")
        lines.extend(format_item(i) for i in vacation_items)
        lines.append("")
    if submission_items:
        lines.append("📄 제출 기한")
        lines.extend(format_item(i) for i in submission_items)
        lines.append("")

    has_undecided = any(i["담당"] == "미정" for i in vacation_items + submission_items)
    if has_undecided:
        lines.append("미정인 항목은 오늘 안에 정해주세요")

    return "\n".join(lines).rstrip()


def send_to_slack(webhook_url, text):
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status


def main():
    parser = argparse.ArgumentParser(description="유치원 일정 슬랙 알림")
    parser.add_argument("--dry-run", action="store_true", help="발송하지 않고 메시지만 출력")
    parser.add_argument("--date", help="오늘 날짜를 이걸로 가정한다 (YYYY-MM-DD)")
    args = parser.parse_args()

    today = (
        datetime.date.fromisoformat(args.date) if args.date
        else datetime.date.today()
    )

    global mod
    mod = load_notion()
    targets = load_targets()

    vacation_items, submission_items = collect(mod, targets, today)
    message = build_message(vacation_items, submission_items)

    if message is None:
        print(f"[{today}] 오늘 알릴 것이 없습니다 (D-7/D-3/D-1 해당 항목 없음).")
        return

    print(message)

    if args.dry_run:
        print("\n(연습) 위 메시지는 발송되지 않았습니다.")
        return

    webhook = load_slack_webhook()
    if not webhook:
        sys.exit(
            "\nSLACK_WEBHOOK_URL 이 없습니다. .env 에 추가해주세요:\n"
            "  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..."
        )

    status = send_to_slack(webhook, message)
    print(f"\n슬랙 발송 완료 (status {status})")


if __name__ == "__main__":
    main()
