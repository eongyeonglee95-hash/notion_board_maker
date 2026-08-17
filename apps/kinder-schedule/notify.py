#!/usr/bin/env python3
"""
노션의 유치원 일정 · 제출·준비물 · 급식 식단을 확인해서 슬랙으로 알린다.

의존성 없음(표준 라이브러리만 사용). notion.py 를 옆에서 불러 쓴다.
Slack Block Kit(https://api.slack.com/block-kit) 으로 메시지를 만든다 —
헤더·구분선·불릿이 있어야 슬랙 앱에서 한눈에 들어온다.

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
CONFIG_JSON = os.path.join(HERE, "config.json")

D_DAYS = (7, 3, 1)  # 휴가필요·제출물 알림은 이 날짜에만 발송한다

# 깃허브 액션 러너는 UTC 로 돈다. 아침 잡은 21:30 UTC(=KST 다음날 06:30)에 실행되므로
# date.today() 를 그대로 쓰면 하루 전 날짜로 알림이 나간다. 반드시 KST 로 계산한다.
KST = datetime.timezone(datetime.timedelta(hours=9))

COLOR_KINDER = "#3182f6"  # 메시지 왼쪽 색 띠 — 유치원은 파랑
ICON_KINDER = ":school:"  # 아바타. 학원 알림과 한눈에 구분하려는 것
NAME_KINDER = "유치원 알림"


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


def load_config():
    if not os.path.exists(CONFIG_JSON):
        sys.exit(
            f"config.json 을 찾을 수 없습니다: {CONFIG_JSON}\n"
            "config.example.json 을 config.json 으로 복사해서 값을 채워주세요."
        )
    with open(CONFIG_JSON, encoding="utf-8") as f:
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
        공휴일 = prop_checkbox(row, "공휴일")
        is_vacation = prop_checkbox(row, "휴가") and not 공휴일

        item = {
            "이름": prop_text(row, "일정명"),
            "날짜": d,
            "종류": prop_select(row, "종류") or "기타",
            "담당": prop_select(row, "담당") or "미정",
            "dday": dday,
            "공휴일": 공휴일,
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
        공휴일 = prop_checkbox(row, "공휴일")
        schedule_items.append({
            "이름": prop_text(row, "일정명"),
            "날짜": d,
            "종류": prop_select(row, "종류") or "기타",
            "휴가": prop_checkbox(row, "휴가") and not 공휴일,
            "공휴일": 공휴일,
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


def find_next_item(mod, targets, after):
    """after 이후 가장 빠른 유치원 일정 또는 제출·준비물 마감을 찾는다. 없으면 None."""
    candidates = []

    ds_schedule = targets["유치원 일정"]["data_source_id"]
    for row in query_all(mod, ds_schedule):
        d = prop_date_start(row, "날짜")
        if d and d > after:
            candidates.append((d, "다음 일정", prop_text(row, "일정명")))

    ds_submission = targets["제출·준비물"]["data_source_id"]
    for row in query_all(mod, ds_submission):
        if prop_checkbox(row, "완료"):
            continue
        d = prop_date_start(row, "마감일")
        if d and d > after:
            candidates.append((d, "다음 마감", prop_text(row, "항목명")))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


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


# ---------------------------------------------------------------------------
# Slack Block Kit 렌더링
# ---------------------------------------------------------------------------

def header_block(text):
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def section_mrkdwn(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def divider_block():
    return {"type": "divider"}


def context_block(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def bullet_daily(item):
    """D-day 있는 항목(휴가필요·제출물) 한 줄."""
    d = item["날짜"]
    담당 = item["담당"]
    담당_str = f"담당: {담당} ❗" if 담당 == "미정" else f"담당: {담당}"
    return f"• *{d.month}/{d.day}({weekday_kr(d)})* {item['이름']}  `D-{item['dday']}` · {담당_str}"


def bullet_range(item, show_vacation=False):
    """기간(월간·주간·내일) 항목 한 줄. 종류 표시, 필요하면 휴가 배지."""
    d = item["날짜"]
    담당 = item.get("담당", "미정")
    담당_str = f"담당: {담당} ❗" if 담당 == "미정" else f"담당: {담당}"
    종류 = item.get("종류")
    종류_str = f"_{종류}_ " if 종류 else ""
    if show_vacation and item.get("공휴일"):
        warn = " 🎌공휴일"
    elif show_vacation and item.get("휴가"):
        warn = " ⚠️휴가"
    else:
        warn = ""
    return f"• *{d.month}/{d.day}({weekday_kr(d)})* {종류_str}{item['이름']}{warn} — {담당_str}"


def _strip_trailing_divider(blocks):
    if blocks and blocks[-1]["type"] == "divider":
        blocks.pop()
    return blocks


def notion_link_block(dashboard_url):
    return context_block(f"🔗 <{dashboard_url}|노션에서 자세히 보기>")


def build_blocks_daily(vacation_items, tomorrow_items, submission_items, tomorrow_meal, today, dashboard_url):
    if not vacation_items and not tomorrow_items and not submission_items and not tomorrow_meal:
        return None, None

    blocks = [header_block(f"🏫 유치원 알림 · {today.month}/{today.day}({weekday_kr(today)})")]

    if vacation_items:
        lines = ["*⚠️ 휴가 필요*"] + [bullet_daily(i) for i in vacation_items]
        blocks.append(section_mrkdwn("\n".join(lines)))
        blocks.append(divider_block())
    if tomorrow_items:
        lines = ["*📌 내일 있는 일정*"] + [bullet_range(i) for i in tomorrow_items]
        blocks.append(section_mrkdwn("\n".join(lines)))
        blocks.append(divider_block())
    if submission_items:
        lines = ["*📄 제출 기한*"] + [bullet_daily(i) for i in submission_items]
        blocks.append(section_mrkdwn("\n".join(lines)))
        blocks.append(divider_block())

    has_undecided = any(
        i["담당"] == "미정" for i in vacation_items + submission_items
    )
    if has_undecided:
        blocks.append(context_block("⚠️ 미정인 항목은 오늘 안에 정해주세요"))

    if tomorrow_meal:
        lunch, snack = tomorrow_meal
        meal_text = "🍱 내일 식단"
        if lunch:
            meal_text += f": {lunch}"
        if snack:
            meal_text += f" · 간식 {snack}"
        blocks.append(context_block(meal_text))

    _strip_trailing_divider(blocks)
    blocks.append(notion_link_block(dashboard_url))
    fallback = f"유치원 알림 · {today.month}/{today.day}({weekday_kr(today)})"
    return blocks, fallback


def build_blocks_period(title, schedule_items, submission_items, empty_text, dashboard_url, next_item=None):
    blocks = [header_block(title)]

    if not schedule_items and not submission_items:
        blocks.append(section_mrkdwn(f"📭 *{empty_text}*"))
        if next_item:
            d, label, name = next_item
            blocks.append(context_block(f"👉 {label}: {d.month}/{d.day}({weekday_kr(d)}) {name}"))
        blocks.append(notion_link_block(dashboard_url))
        return blocks, title

    if schedule_items:
        lines = ["*📅 일정*"] + [bullet_range(i, show_vacation=True) for i in schedule_items]
        blocks.append(section_mrkdwn("\n".join(lines)))
        blocks.append(divider_block())
    if submission_items:
        lines = ["*📄 마감인 제출·준비물*"] + [bullet_range(i) for i in submission_items]
        blocks.append(section_mrkdwn("\n".join(lines)))
        blocks.append(divider_block())

    _strip_trailing_divider(blocks)
    blocks.append(notion_link_block(dashboard_url))
    return blocks, title


def send_to_slack(webhook_url, blocks, fallback):
    # 왼쪽 색 띠. 학원 알림(노랑·빨강)과 한눈에 구분하기 위한 것이다.
    payload = {
        "text": fallback,
        "attachments": [{"color": COLOR_KINDER, "blocks": blocks}],
        "icon_emoji": ICON_KINDER,
        "username": NAME_KINDER,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status


def print_blocks(blocks):
    for b in blocks:
        t = b["type"]
        if t == "header":
            print(f"# {b['text']['text']}")
        elif t == "section":
            print(b["text"]["text"])
        elif t == "divider":
            print("---")
        elif t == "context":
            print("  " + " / ".join(e["text"] for e in b["elements"]))


def send_or_print(webhook, blocks, fallback, dry_run, label):
    if blocks is None:
        print(f"[{label}] 알릴 것이 없습니다.")
        return
    print(f"[{label}] {fallback}")
    print_blocks(blocks)
    if dry_run:
        print("\n(연습) 위 메시지는 발송되지 않았습니다.\n")
        return
    if not webhook:
        sys.exit(
            "\nSLACK_WEBHOOK_URL 이 없습니다. .env 에 추가해주세요:\n"
            "  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..."
        )
    status = send_to_slack(webhook, blocks, fallback)
    print(f"\n슬랙 발송 완료 (status {status})\n")


def run_daily(mod, targets, today, webhook, dry_run, dashboard_url):
    vacation_items, tomorrow_items, submission_items, tomorrow_meal = collect_daily(
        mod, targets, today
    )
    blocks, fallback = build_blocks_daily(
        vacation_items, tomorrow_items, submission_items, tomorrow_meal, today, dashboard_url
    )
    send_or_print(webhook, blocks, fallback, dry_run, f"{today} 데일리")

    if today.day == 1:
        start, end = month_range(today.year, today.month)
        schedule_items, submission_items = collect_range(mod, targets, start, end)
        next_item = None if (schedule_items or submission_items) else find_next_item(mod, targets, end)
        blocks, fallback = build_blocks_period(
            f"🏫 {today.month}월 유치원 알림 (월간 요약)",
            schedule_items, submission_items,
            "이번 달은 특별한 일정 없어요",
            dashboard_url,
            next_item,
        )
        send_or_print(webhook, blocks, fallback, dry_run, f"{today} 월간")


def run_weekly(mod, targets, today, webhook, dry_run, dashboard_url):
    start = today + datetime.timedelta(days=1)
    end = today + datetime.timedelta(days=7)
    schedule_items, submission_items = collect_range(mod, targets, start, end)
    next_item = None if (schedule_items or submission_items) else find_next_item(mod, targets, end)
    label = f"{start.month}/{start.day}~{end.month}/{end.day}"
    blocks, fallback = build_blocks_period(
        f"🏫 {label} 유치원 알림 (주간 요약)",
        schedule_items, submission_items,
        "다음 주는 특별한 일정 없어요",
        dashboard_url,
        next_item,
    )
    send_or_print(webhook, blocks, fallback, dry_run, f"{today} 주간")


def main():
    parser = argparse.ArgumentParser(description="유치원 일정 슬랙 알림")
    parser.add_argument("--dry-run", action="store_true", help="발송하지 않고 메시지만 출력")
    parser.add_argument("--date", help="오늘 날짜를 이걸로 가정한다 (YYYY-MM-DD)")
    parser.add_argument("--weekly", action="store_true", help="주간 다이제스트 모드")
    args = parser.parse_args()

    today = (
        datetime.date.fromisoformat(args.date) if args.date
        else datetime.datetime.now(KST).date()
    )

    mod = load_notion()
    targets = load_targets()
    webhook = load_slack_webhook()
    dashboard_url = load_config()["노션_대시보드_URL"]

    if args.weekly:
        run_weekly(mod, targets, today, webhook, args.dry_run, dashboard_url)
    else:
        run_daily(mod, targets, today, webhook, args.dry_run, dashboard_url)


if __name__ == "__main__":
    main()
