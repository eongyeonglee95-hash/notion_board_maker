#!/usr/bin/env python3
"""
하원이 임박한 학원 일정이 있으면 슬랙으로 알린다.

하원까지 35분 이내면 알리고, 이미 보낸 항목은 Firestore 발송기록으로 걸러낸다.
GitHub Actions 크론이 */5 로 걸어도 실제로는 20~50분 간격으로 뜨기 때문에,
창을 넓게 잡아 놓쳐도 다음 실행이 줍게 하고 중복은 기록으로 막는 구조다.

사용법:
  python3 apps/kinder-academy/notify_imminent.py --dry-run --use-sample-data --now 2026-08-15T11:30
  python3 apps/kinder-academy/notify_imminent.py   # 5분마다 실행 (GitHub Actions)
"""

import argparse
import datetime

import academy_common as ac


def minutes_until(now, pickup_dt):
    return (pickup_dt - now).total_seconds() / 60


def should_alert(now, pickup_dt):
    """하원까지 남았고, 남은 시간이 알림 창 안이면 True."""
    m = minutes_until(now, pickup_dt)
    return 0 < m <= ac.PICKUP_ALERT_WINDOW_MINUTES


def build_blocks(imminent, day_label, lead_minutes):
    # 슬랙에서 글자 크기를 키울 수 있는 블록은 header 뿐이다. 제목은 굵게 한 번만 쓰고,
    # 정작 급할 때 봐야 하는 하원 시간을 header 로 올려 가장 크게 보이게 한다.
    #
    # 실행 시각이 크론 지연으로 흔들려서 "30분 전"이 늘 맞지는 않는다.
    # 실제로 남은 시간을 5분 단위로 반올림해 적는다.
    lead = max(5, round(lead_minutes / 5) * 5)
    blocks = [
        ac.section_mrkdwn(
            f"*🚨 하원 {lead}분 전*\n{ac.kids_label()} 곧 도착해요. 지금 준비해 주세요!"
        )
    ]

    for s in imminent:
        blocks.append(ac.header_block(f"{ac.clock_emoji(s['endTime'])} {s['endTime']} 하원"))
        lines = [ac.academy_row(s)]
        lines.extend(ac.pickup_rows(s))
        blocks.append(ac.section_mrkdwn("\n".join(lines)))

    mentions = ac.mention_text()
    if mentions:
        blocks.append(ac.section_mrkdwn(mentions))

    blocks.append(ac.app_button_block())
    names = ", ".join(s["academy"] for s in imminent)
    fallback = f"하원 {lead}분 전 · {day_label} · {names}"
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
    leads = []
    for s in today_items:
        if not s["endTime"]:
            continue
        pickup_dt = datetime.datetime.combine(
            now.date(), datetime.time.fromisoformat(s["endTime"]), tzinfo=ac.KST
        )
        if should_alert(now, pickup_dt):
            imminent.append(s)
            leads.append(minutes_until(now, pickup_dt))

    if not imminent:
        print(f"[{now}] 하원이 임박한 학원 일정이 없습니다.")
        return

    # 이미 보낸 항목은 걸러낸다. 연습 실행과 샘플 데이터는 기록을 남기지 않는다.
    claimed = []
    if not args.dry_run and not args.use_sample_data:
        fresh = []
        for s, lead in zip(imminent, leads):
            key = f"pickup-{now.date().isoformat()}-{s['id']}"
            if ac.claim_notification(key):
                claimed.append(key)
                fresh.append((s, lead))
        if not fresh:
            print(f"[{now}] 임박한 일정이 있지만 이미 알림을 보냈습니다.")
            return
        imminent = [s for s, _ in fresh]
        leads = [lead for _, lead in fresh]

    blocks, fallback = build_blocks(imminent, day_label, min(leads))
    webhook = ac.load_slack_webhook()
    try:
        ac.send_or_print(
            webhook, blocks, fallback, args.dry_run, f"{now} 하원임박",
            color=ac.COLOR_IMMINENT, icon=ac.ICON_IMMINENT, name=ac.NAME_IMMINENT,
        )
    except SystemExit:
        # 기록만 남고 발송이 실패하면 그 날 알림이 통째로 사라진다. 되돌려서
        # 다음 실행이 다시 시도하게 한다.
        for key in claimed:
            ac.release_notification(key)
        raise


if __name__ == "__main__":
    main()
