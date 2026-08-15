#!/usr/bin/env python3
"""
매일 아침 한 번 돌면서 두 가지를 한다.

  1. 오늘 요일의 학원 스케줄을 슬랙으로 요약해서 바로 보낸다.
  2. 오늘 하원 30분 전 시각으로 임박 알림을 슬랙에 "예약"해 둔다.

예약을 쓰는 이유: 웹훅으로는 "지금" 밖에 못 보내는데, 크론을 촘촘히 걸어도
GitHub Actions 는 실제로 20~50분씩 밀려서 하원 30분 전을 정확히 맞출 수 없다.
chat.scheduleMessage 로 걸어두면 발송 시각은 슬랙 서버가 지킨다.

의존성: firebase-admin (requirements.txt). 노션이 아니라 Firestore
(KidsPlanner 학원 스케줄 앱의 데이터)를 읽는다.

사용법:
  python3 apps/kinder-academy/notify_daily.py --dry-run
  python3 apps/kinder-academy/notify_daily.py --dry-run --use-sample-data --date 2026-08-18
  python3 apps/kinder-academy/notify_daily.py   # 매일 아침 실행 (GitHub Actions)
"""

import argparse
import datetime

import academy_common as ac


def build_blocks(schedules_today, day_label, weekday_kr):
    blocks = [ac.header_block(f"🎒 학원 스케줄 · {day_label}({weekday_kr})")]

    if not schedules_today:
        blocks.append(ac.section_mrkdwn("🚶 오늘은 학원 없이 도보하원 하는 날이에요"))
        blocks.append(ac.app_button_block())
        return blocks, f"학원 스케줄 · {day_label}({weekday_kr}) — 도보하원"

    for i, s in enumerate(schedules_today):
        # 학원명 / 하원시간 / 하차위치 / 하원도우미를 각각 한 줄씩. 아침에 훑을 때
        # 필요한 건 이 넷뿐이라 등원시간·연락처 같은 나머지는 앱 버튼으로 넘긴다.
        lines = [ac.academy_row(s)]
        lines.append(
            f"{ac.clock_emoji(s['endTime'])} 하원 {s['endTime']}" if s["endTime"]
            else "🕐 하원 미정"
        )
        lines.extend(ac.pickup_rows(s))
        blocks.append(ac.section_mrkdwn("\n".join(lines)))
        if i < len(schedules_today) - 1:
            blocks.append(ac.divider_block())

    blocks.append(ac.app_button_block())
    fallback = f"학원 스케줄 · {day_label}({weekday_kr}) — {len(schedules_today)}건"
    return blocks, fallback


def pickup_alert_time(today, end_time):
    """하원 시각에서 PICKUP_LEAD_MINUTES 를 뺀 시각. 시각을 못 읽으면 None."""
    try:
        pickup = datetime.datetime.combine(
            today, datetime.time.fromisoformat(end_time), tzinfo=ac.KST
        )
    except ValueError:
        return None
    return pickup - datetime.timedelta(minutes=ac.PICKUP_LEAD_MINUTES)


def schedule_pickup_alerts(token, channel, schedules_today, today, now, dry_run,
                           pickup_in=None, real_now=None):
    """오늘 하원 30분 전 알림들을 슬랙에 예약한다.

    pickup_in 을 주면 테스트 모드다. 하원 시각을 무시하고 지금부터 그만큼 뒤로
    건다. 예약이 실제로 그 시각에 도착하는지 몇 시간 기다리지 않고 확인하려고.
    """
    planned = []

    if pickup_in is not None:
        base = real_now + datetime.timedelta(minutes=pickup_in)
        # 여러 건이면 1분씩 벌려서 한꺼번에 쏟아지지 않게 한다.
        planned = [(s, base + datetime.timedelta(minutes=i))
                   for i, s in enumerate(schedules_today)]
        print(f"  (테스트) 하원 시각 무시하고 {pickup_in}분 뒤부터 예약합니다.")
        if not planned:
            print("  오늘 학원이 없어 예약할 게 없습니다.")
            return
        _send_planned(token, channel, planned, dry_run)
        return

    for s in schedules_today:
        if not s["endTime"]:
            continue
        alert_at = pickup_alert_time(today, s["endTime"])
        if alert_at is None:
            print(f"  · {s['academy']}: 하원 시각 '{s['endTime']}' 을 읽을 수 없어 건너뜁니다.")
            continue
        if alert_at <= now:
            print(f"  · {s['academy']}: 알림 시각 {alert_at:%H:%M} 이 이미 지나 건너뜁니다.")
            continue
        planned.append((s, alert_at))

    if not planned:
        print("  예약할 하원 알림이 없습니다.")
        return

    _send_planned(token, channel, planned, dry_run)


def _send_planned(token, channel, planned, dry_run):
    for s, alert_at in planned:
        blocks, fallback = ac.build_pickup_blocks(s)
        print(f"  · {alert_at:%H:%M} 예약 — {fallback}")
        if dry_run:
            continue
        ac.schedule_message(
            token, channel, alert_at.timestamp(), blocks, fallback,
            color=ac.COLOR_IMMINENT, icon=ac.ICON_IMMINENT, name=ac.NAME_IMMINENT,
        )

    if dry_run:
        print("  (연습) 위 예약은 걸리지 않았습니다.")
    else:
        print(f"  하원 알림 {len(planned)}건 예약 완료.")


def main():
    parser = argparse.ArgumentParser(description="학원 스케줄 아침 요약 + 하원 알림 예약")
    parser.add_argument("--dry-run", action="store_true", help="발송·예약하지 않고 출력만")
    parser.add_argument("--date", help="오늘 날짜를 이걸로 가정한다 (YYYY-MM-DD)")
    parser.add_argument("--use-sample-data", action="store_true", help="Firestore 대신 sample_schedules.json 사용")
    parser.add_argument("--pickup-in", type=int, metavar="분",
                        help="테스트용 — 하원 시각 무시하고 지금부터 N분 뒤로 예약")
    args = parser.parse_args()

    real_now = ac.now_kst()
    now = real_now
    today = datetime.date.fromisoformat(args.date) if args.date else now.date()
    if args.date:
        # 날짜를 갈아끼우면 "지금"도 그 날 아침으로 옮겨야 예약 시각 비교가 맞는다.
        now = datetime.datetime.combine(today, datetime.time(7, 0), tzinfo=ac.KST)
    weekday_kr = "월화수목금토일"[today.weekday()]
    day_label = f"{today.month}/{today.day}"

    schedules = ac.load_sample_schedules() if args.use_sample_data else ac.fetch_schedules()
    today_items = ac.schedules_for_day(schedules, weekday_kr) if weekday_kr in ac.DAYS else []

    blocks, fallback = build_blocks(today_items, day_label, weekday_kr)

    token = ac.load_bot_token()
    channel = ac.load_channel()

    # --- 1. 아침 요약 발송 -------------------------------------------------
    print(f"[{today} 학원 아침요약] {fallback}")
    ac.print_blocks(blocks)
    if args.dry_run:
        print("\n(연습) 위 메시지는 발송되지 않았습니다.\n")
    elif token and channel:
        ac.post_message(token, channel, blocks, fallback,
                        color=ac.COLOR_DAILY, icon=ac.ICON_DAILY, name=ac.NAME_DAILY)
        print("\n슬랙 발송 완료 (chat.postMessage)\n")
    else:
        webhook = ac.load_slack_webhook()
        if not webhook:
            raise SystemExit("SLACK_BOT_TOKEN_ACADEMY 도 SLACK_WEBHOOK_URL_ACADEMY 도 없습니다.")
        status = ac.send_to_slack(webhook, blocks, fallback,
                                  ac.COLOR_DAILY, ac.ICON_DAILY, ac.NAME_DAILY)
        print(f"\n슬랙 발송 완료 (웹훅, status {status})\n")

    # --- 2. 하원 알림 예약 -------------------------------------------------
    print("하원 알림 예약:")
    if not token or not channel:
        print("  봇 토큰/채널이 없어 건너뜁니다 "
              "(SLACK_BOT_TOKEN_ACADEMY, SLACK_CHANNEL_ACADEMY 필요).")
        return

    if not args.dry_run:
        # 아침 잡을 두 번 돌려도 같은 알림이 두 번 오지 않도록 오늘 예약을 먼저 지운다.
        # 테스트 모드는 --date 로 날짜를 갈아끼울 수 있으니 진짜 오늘을 기준으로 지운다.
        base = real_now if args.pickup_in is not None else now
        day_end = datetime.datetime.combine(
            base.date(), datetime.time(23, 59), tzinfo=ac.KST)
        removed = ac.clear_scheduled(token, channel, base.timestamp(), day_end.timestamp())
        if removed:
            print(f"  · 기존 예약 {removed}건 취소")
    schedule_pickup_alerts(token, channel, today_items, today, now, args.dry_run,
                           pickup_in=args.pickup_in, real_now=real_now)


if __name__ == "__main__":
    main()
