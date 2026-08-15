#!/usr/bin/env python3
"""
하원 30분 전인 학원 일정이 있으면 슬랙으로 알린다. 10분 간격 cron 실행 전제.

중복 방지: 판정 윈도우 폭(PICKUP_WINDOW_MINUTES=10)을 cron 주기와 똑같이 맞춰서,
연속된 두 실행이 같은 항목을 두 번 잡을 수 없게 한다 — 상태 저장소 없이 "최대 1번"을
보장한다(자세한 증명은 academy_common.py 주석·설계 문서 참고). 대신 GitHub Actions
스케줄이 드물게 지연/스킵되면 알림을 놓칠 수 있다(중복보다 낫다고 판단해 받아들인 트레이드오프).

사용법:
  python3 apps/kinder-academy/notify_imminent.py --dry-run --use-sample-data --now 2026-08-15T11:30
  python3 apps/kinder-academy/notify_imminent.py   # 10분마다 실행 (GitHub Actions)
"""

import argparse
import datetime

import academy_common as ac


def minutes_until(now, pickup_dt):
    return (pickup_dt - now).total_seconds() / 60


def should_alert(now, pickup_dt):
    m = minutes_until(now, pickup_dt)
    lo = ac.PICKUP_LEAD_MINUTES - ac.PICKUP_WINDOW_MINUTES / 2
    hi = ac.PICKUP_LEAD_MINUTES + ac.PICKUP_WINDOW_MINUTES / 2
    return lo <= m < hi


def build_blocks(imminent, day_label):
    blocks = [ac.header_block("⏰ 하원 30분 전이에요")]

    for i, s in enumerate(imminent):
        lines = [f"*{s['academyType']}* {s['academy']} — {s['endTime']} 하원"]
        detail = ac.academy_detail_line(s)
        if detail:
            lines.append(detail)
        blocks.append(ac.section_mrkdwn("\n".join(lines)))
        if i < len(imminent) - 1:
            blocks.append(ac.divider_block())

    mentions = ac.mention_text()
    if mentions:
        blocks.append(ac.section_mrkdwn(mentions))

    blocks.append(ac.app_link_block())
    names = ", ".join(s["academy"] for s in imminent)
    fallback = f"하원 30분 전 · {day_label} · {names}"
    return blocks, fallback


def main():
    parser = argparse.ArgumentParser(description="학원 하원 임박 슬랙 알림")
    parser.add_argument("--dry-run", action="store_true", help="발송하지 않고 메시지만 출력")
    parser.add_argument("--now", help="현재 시각을 이걸로 가정한다 (YYYY-MM-DDTHH:MM, KST)")
    parser.add_argument("--use-sample-data", action="store_true", help="Firestore 대신 sample_schedules.json 사용")
    args = parser.parse_args()

    now = (
        datetime.datetime.fromisoformat(args.now).replace(tzinfo=ac.KST) if args.now
        else ac.now_kst()
    )
    weekday_kr = "월화수목금토일"[now.weekday()]
    day_label = f"{now.month}/{now.day}"

    if weekday_kr not in ac.DAYS:
        print(f"[{now}] {weekday_kr}요일은 학원 일정이 없습니다.")
        return

    schedules = ac.load_sample_schedules() if args.use_sample_data else ac.fetch_schedules()
    today_items = ac.schedules_for_day(schedules, weekday_kr)

    imminent = []
    for s in today_items:
        if not s["endTime"]:
            continue
        pickup_dt = datetime.datetime.combine(
            now.date(), datetime.time.fromisoformat(s["endTime"]), tzinfo=ac.KST
        )
        if should_alert(now, pickup_dt):
            imminent.append(s)

    if not imminent:
        print(f"[{now}] 30분 전인 학원 일정이 없습니다.")
        return

    blocks, fallback = build_blocks(imminent, day_label)
    webhook = ac.load_slack_webhook()
    ac.send_or_print(
        webhook, blocks, fallback, args.dry_run, f"{now} 하원임박",
        color=ac.COLOR_IMMINENT, icon=ac.ICON_IMMINENT, name=ac.NAME_IMMINENT,
    )


if __name__ == "__main__":
    main()
