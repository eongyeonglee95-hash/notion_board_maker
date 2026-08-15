#!/usr/bin/env python3
"""
오늘 요일의 학원 스케줄을 슬랙으로 아침에 요약해서 알린다.

의존성: firebase-admin (requirements.txt). notify.py 와 달리 노션이 아니라
Firestore(KidsPlanner 학원 스케줄 앱의 데이터)를 읽는다.

사용법:
  python3 apps/kinder-academy/notify_daily.py --dry-run
  python3 apps/kinder-academy/notify_daily.py --dry-run --use-sample-data --date 2026-08-15
  python3 apps/kinder-academy/notify_daily.py   # 매일 아침 실행 (GitHub Actions)
"""

import argparse
import datetime

import academy_common as ac


def build_blocks(schedules_today, day_label, weekday_kr):
    blocks = [ac.header_block(f"🎒 학원 스케줄 · {day_label}({weekday_kr})")]

    if not schedules_today:
        blocks.append(ac.section_mrkdwn("🚶 오늘은 학원 없이 도보하원 하는 날이에요"))
        blocks.append(ac.app_link_block())
        return blocks, f"학원 스케줄 · {day_label}({weekday_kr}) — 도보하원"

    for i, s in enumerate(schedules_today):
        # 학원명 / 하원시간 / 하원도우미 / 하차위치를 각각 한 줄씩. 아침에 훑을 때
        # 필요한 건 이 넷뿐이라 등원시간·연락처 같은 나머지는 앱 링크로 넘긴다.
        lines = [ac.academy_row(s)]
        lines.append(f"🕕 하원 {s['endTime'] or '미정'}")
        lines.extend(ac.pickup_rows(s))
        lines.append(ac.BLANK_ROW)
        blocks.append(ac.section_mrkdwn("\n".join(lines)))
        if i < len(schedules_today) - 1:
            blocks.append(ac.divider_block())

    blocks.append(ac.app_link_block())
    fallback = f"학원 스케줄 · {day_label}({weekday_kr}) — {len(schedules_today)}건"
    return blocks, fallback


def main():
    parser = argparse.ArgumentParser(description="학원 스케줄 아침 요약 슬랙 알림")
    parser.add_argument("--dry-run", action="store_true", help="발송하지 않고 메시지만 출력")
    parser.add_argument("--date", help="오늘 날짜를 이걸로 가정한다 (YYYY-MM-DD)")
    parser.add_argument("--use-sample-data", action="store_true", help="Firestore 대신 sample_schedules.json 사용")
    args = parser.parse_args()

    today = (
        datetime.date.fromisoformat(args.date) if args.date
        else ac.now_kst().date()
    )
    weekday_kr = "월화수목금토일"[today.weekday()]
    day_label = f"{today.month}/{today.day}"

    schedules = ac.load_sample_schedules() if args.use_sample_data else ac.fetch_schedules()
    today_items = ac.schedules_for_day(schedules, weekday_kr) if weekday_kr in ac.DAYS else []

    blocks, fallback = build_blocks(today_items, day_label, weekday_kr)

    webhook = ac.load_slack_webhook()
    ac.send_or_print(
        webhook, blocks, fallback, args.dry_run, f"{today} 학원 아침요약",
        color=ac.COLOR_DAILY, icon=ac.ICON_DAILY, name=ac.NAME_DAILY,
    )


if __name__ == "__main__":
    main()
