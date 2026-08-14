#!/usr/bin/env python3
"""
노션의 유치원 일정 · 제출·준비물 · 급식 식단을 확인해서 슬랙으로 알린다.

의존성 없음(표준 라이브러리만 사용). notion.py 를 옆에서 불러 쓴다.

사용법:
  python3 apps/kinder-schedule/notify.py --dry-run              # 발송 없이 메시지만 출력
  python3 apps/kinder-schedule/notify.py --dry-run --date 2026-09-12  # 특정 날짜인 척
  python3 apps/kinder-schedule/notify.py                        # 매일 아침 실행 (GitHub Actions)
  python3 apps/kinder-schedule/notify.py --weekly                # 매주 일요일 저녁 실행 (GitHub Actions)

.env 에 SLACK_WEBHOOK_URL 이 있어야 실제 발송이 된다 (--dry-run 은 없어도 된다).

매일 실행(플래그 없음)은:
  - 휴가 필요 유치원 일정 · 미완료 제출물을 D-7/D-3/D-1 기준으로 알린다
  - 내일 있는 유치원 일정 전체(휴가 필요 여부 무관)와 내일 급식도 같이 알린다
  - 오늘이 매월 1일이면 이번 달 전체 요약도 추가로 보낸다
  - 알릴 게 하나도 없으면 조용히 스킵한다

--weekly 실행은 "오늘"의 다음 월요일부터 그 다음 일요일까지 7일간의 유치원 일정 전체와
그 기간 마감인 제출물을 알린다. 알릴 게 없어도 "특별한 일정 없어요"를 보낸다(봇 생존 확인용).
"""

import argparse
import calendar
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

D_DAYS = (7, 3, 1)  # 휴가필요·제출물 알림은 이 날짜에만 발송한다


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


def month_range(year, month):
    """해당 년월의 (첫날, 마지막날) date 튜플."""
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last_day)


def collect_daily(mod, targets, today):
    """매일 실행분: 휴가필요 D-7/D-3/D-1, 내일 있는 일정 전체, 제출물 D-7/D-3/D-1, 내일 식단."""
    vacation_items = []
    tomorrow_items = []
    submission_items = []

    ds_schedule = targets["유치원 일정"]["data_source_id"]
    schedule_rows = query_all(mod, ds_schedule)
    for row in schedule_rows:
        d = prop_date_start(row, "날짜")
        if not d:
            continue
        dday = (d - today).days
        is_vacation = prop_checkbox(row, "휴가")

        item = {
            "이름": prop_text(row, "일정명"),
            "날짜": d,
            "종류": prop_select(row, "종류") or "기타",
            "담당": prop_select(row, "담당") or "미정",
            "dday": dday,
        }

        if is_vacation and dday in D_DAYS:
            vacation_items.append(item)
        if dday == 1 and not is_vacation:
            tomorrow_items.append(item)

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
    tomorrow_items.sort(key=lambda x: x["이름"])
    submission_items.sort(key=lambda x: x["dday"])

    tomorrow = today + datetime.timedelta(days=1)
    tomorrow_meal = find_meal(mod, targets, tomorrow)

    return vacation_items, tomorrow_items, submission_items, tomorrow_meal


def collect_range(mod, targets, start, end):
    """[start, end] 구간(양끝 포함)의 유치원 일정 전체 + 마감인 제출물. 월간/주간 공용."""
    schedule_items = []
    ds_schedule = targets["유치원 일정"]["data_source_id"]
    for row in query_all(mod, ds_schedule):
        d = prop_date_start(row, "날짜")
        if not d or not (start <= d <= end):
            continue
        schedule_items.append({
            "이름": prop_text(row, "일정명"),
            "날짜": d,
            "종류": prop_select(row, "종류") or "기타",
            "휴가": prop_checkbox(row, "휴가"),
            "담당": prop_select(row, "담당") or "미정",
        })

    submission_items = []
    ds_submission = targets["제출·준비물"]["data_source_id"]
    for row in query_all(mod, ds_submission):
        if prop_checkbox(row, "완료"):
            continue
        d = prop_date_start(row, "마감일")
        if not d or not (start <= d <= end):
            continue
        submission_items.append({
            "이름": prop_text(row, "항목명"),
            "날짜": d,
            "담당": prop_select(row, "담당") or "미정",
        })

    schedule_items.sort(key=lambda x: x["날짜"])
    submission_items.sort(key=lambda x: x["날짜"])
    return schedule_items, submission_items


def find_meal(mod, targets, date):
    """급식 식단에서 해당 날짜 한 행을 찾아 (점심, 오후간식) 을 돌려준다. 없으면 None."""
    ds_meal = targets.get("급식 식단", {}).get("data_source_id")
    if not ds_meal:
        return None
    for row in query_all(mod, ds_meal):
        d = prop_date_start(row, "일자")
        if d == date:
            return prop_text(row, "점심"), prop_text(row, "오후간식")
    return None


def format_daily_item(item):
    d = item["날짜"]
    date_str = f"{d.month}/{d.day}({weekday_kr(d)})"
    담당 = item["담당"]
    담당_str = f"담당: {담당} ❗" if 담당 == "미정" else f"담당: {담당}"
    return f"  {date_str} {item['이름']}  — D-{item['dday']} · {담당_str}"


def format_range_item(item, show_vacation=False):
    d = item["날짜"]
    date_str = f"{d.month}/{d.day}({weekday_kr(d)})"
    담당 = item.get("담당", "미정")
    담당_str = f"담당: {담당} ❗" if 담당 == "미정" else f"담당: {담당}"
    tag = f"[{item['종류']}]" if "종류" in item else ""
    warn = " ⚠️휴가" if item.get("휴가") and show_vacation else ""
    return f"  {date_str} {tag}{item['이름']}{warn}  — {담당_str}"


def build_daily_message(vacation_items, tomorrow_items, submission_items, tomorrow_meal):
    if not vacation_items and not tomorrow_items and not submission_items:
        return None

    lines = ["🏫 유치원 알림", ""]
    if vacation_items:
        lines.append("⚠️ 휴가 필요")
        lines.extend(format_daily_item(i) for i in vacation_items)
        lines.append("")
    if tomorrow_items:
        lines.append("📌 내일 있는 일정")
        lines.extend(format_range_item(i) for i in tomorrow_items)
        lines.append("")
    if submission_items:
        lines.append("📄 제출 기한")
        lines.extend(format_daily_item(i) for i in submission_items)
        lines.append("")

    has_undecided = any(
        i["담당"] == "미정" for i in vacation_items + submission_items
    )
    if has_undecided:
        lines.append("미정인 항목은 오늘 안에 정해주세요")
        lines.append("")

    if tomorrow_meal:
        lunch, snack = tomorrow_meal
        meal_line = "🍱 내일 식단"
        if lunch:
            meal_line += f": {lunch}"
        if snack:
            meal_line += f" · 간식 {snack}"
        lines.append(meal_line)

    return "\n".join(lines).rstrip()


def build_period_message(title, schedule_items, submission_items, empty_text):
    lines = [title, ""]

    if not schedule_items and not submission_items:
        lines.append(empty_text)
        return "\n".join(lines).rstrip()

    if schedule_items:
        lines.append("📅 일정")
        lines.extend(format_range_item(i, show_vacation=True) for i in schedule_items)
        lines.append("")
    if submission_items:
        lines.append("📄 마감인 제출·준비물")
        lines.extend(format_range_item(i) for i in submission_items)
        lines.append("")

    return "\n".join(lines).rstrip()


def send_to_slack(webhook_url, text):
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status


def send_or_print(webhook, message, dry_run, label):
    if message is None:
        print(f"[{label}] 알릴 것이 없습니다.")
        return
    print(f"[{label}]")
    print(message)
    if dry_run:
        print("\n(연습) 위 메시지는 발송되지 않았습니다.\n")
        return
    if not webhook:
        sys.exit(
            "\nSLACK_WEBHOOK_URL 이 없습니다. .env 에 추가해주세요:\n"
            "  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..."
        )
    status = send_to_slack(webhook, message)
    print(f"\n슬랙 발송 완료 (status {status})\n")


def run_daily(mod, targets, today, webhook, dry_run):
    vacation_items, tomorrow_items, submission_items, tomorrow_meal = collect_daily(
        mod, targets, today
    )
    message = build_daily_message(
        vacation_items, tomorrow_items, submission_items, tomorrow_meal
    )
    send_or_print(webhook, message, dry_run, f"{today} 데일리")

    if today.day == 1:
        start, end = month_range(today.year, today.month)
        schedule_items, submission_items = collect_range(mod, targets, start, end)
        message = build_period_message(
            f"🏫 {today.month}월 유치원 알림 (월간 요약)",
            schedule_items, submission_items,
            "이번 달은 특별한 일정 없어요",
        )
        send_or_print(webhook, message, dry_run, f"{today} 월간")


def run_weekly(mod, targets, today, webhook, dry_run):
    start = today + datetime.timedelta(days=1)
    end = today + datetime.timedelta(days=7)
    schedule_items, submission_items = collect_range(mod, targets, start, end)
    label = f"{start.month}/{start.day}~{end.month}/{end.day}"
    message = build_period_message(
        f"🏫 {label} 유치원 알림 (주간 요약)",
        schedule_items, submission_items,
        "다음 주는 특별한 일정 없어요",
    )
    send_or_print(webhook, message, dry_run, f"{today} 주간")


def main():
    parser = argparse.ArgumentParser(description="유치원 일정 슬랙 알림")
    parser.add_argument("--dry-run", action="store_true", help="발송하지 않고 메시지만 출력")
    parser.add_argument("--date", help="오늘 날짜를 이걸로 가정한다 (YYYY-MM-DD)")
    parser.add_argument("--weekly", action="store_true", help="주간 다이제스트 모드")
    args = parser.parse_args()

    today = (
        datetime.date.fromisoformat(args.date) if args.date
        else datetime.date.today()
    )

    mod = load_notion()
    targets = load_targets()
    webhook = load_slack_webhook() if not args.dry_run else load_slack_webhook()

    if args.weekly:
        run_weekly(mod, targets, today, webhook, args.dry_run)
    else:
        run_daily(mod, targets, today, webhook, args.dry_run)


if __name__ == "__main__":
    main()
