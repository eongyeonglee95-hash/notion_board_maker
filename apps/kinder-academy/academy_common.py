"""
학원 스케줄(Firestore) 조회 + Slack Block Kit 렌더링 공용 헬퍼.

kinder-schedule/notify.py 와 데이터 소스(Firestore vs 노션)가 달라 헬퍼를 공유하지
않고 의도적으로 복제한다 — 이 저장소의 기존 관례(build_ics.py·mark_past_due.py·
notify.py가 각자 query_all 을 따로 갖는 것)와 일치한다.

일정은 "그 날짜"가 아니라 "그 요일마다 매주 반복"으로 저장된다(KidsPlanner
script.js 의 normalizeSchedule 이 렌더링 때마다 date 를 그 주의 실제 날짜로
재계산한다). 그래서 여기서도 날짜가 아니라 요일(day)로 필터링한다.
"""

import datetime
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

SERVICE_ACCOUNT_JSON = os.path.join(HERE, "firebase-service-account.json")
SAMPLE_DATA_JSON = os.path.join(HERE, "sample_schedules.json")

FIRESTORE_COLLECTION = "schedules"
ACADEMY_APP_URL = "https://kids-academy-planner.web.app/"
PICKUP_LEAD_MINUTES = 30
PICKUP_WINDOW_MINUTES = 10  # notify_imminent.py 의 cron 주기와 반드시 같아야 한다

# 메시지 왼쪽 색 띠. 여러 알림이 쌓였을 때 색으로 종류를 구분한다.
COLOR_DAILY = "#f2c744"    # 학원 아침 요약 — 노랑
COLOR_IMMINENT = "#e01e5a"  # 하원 임박 — 빨강(지금 움직여야 하는 것)

# 메시지 아바타(이모지)와 표시 이름. 채널에 알림이 섞여 쌓이므로,
# 색 띠보다 크게 보이는 아바타로 종류를 구분한다.
ICON_DAILY = ":school_satchel:"
NAME_DAILY = "학원 스케줄"
ICON_IMMINENT = ":rotating_light:"
NAME_IMMINENT = "하원 알림"

# 하원 임박 알림에서 멘션할 사람들의 슬랙 멤버 ID.
# 채널 메시지는 멘션이 없으면 푸시가 안 울려서, 급한 알림만 멘션을 붙인다.
# 슬랙 프로필 > 더보기(⋯) > 멤버 ID 복사 로 얻는다.
MENTION_USER_IDS = []

KST = datetime.timezone(datetime.timedelta(hours=9))

DAYS = ["월", "화", "수", "목", "금", "토"]


def now_kst():
    return datetime.datetime.now(KST)


def today_weekday_kr(dt):
    """월=0..일=6 인 파이썬 weekday() 를 한글 요일로 바꾼다."""
    return "월화수목금토일"[dt.weekday()]


def load_slack_webhook():
    """학원 알림용 웹훅을 읽는다.

    슬랙에서 유치원(KidsPlanner)과 학원(KidsAcademy)을 다른 앱으로 분리했으므로
    SLACK_WEBHOOK_URL_ACADEMY 를 먼저 본다. 없으면 유치원과 같은 웹훅으로 떨어진다.
    """
    for key in ("SLACK_WEBHOOK_URL_ACADEMY", "SLACK_WEBHOOK_URL"):
        url = os.environ.get(key)
        if url:
            return url.strip().strip('"').strip("'")

    env_path = os.path.join(REPO, ".env")
    if os.path.exists(env_path):
        found = {}
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key in ("SLACK_WEBHOOK_URL_ACADEMY", "SLACK_WEBHOOK_URL"):
                    found[key] = value.strip().strip('"').strip("'")
        for key in ("SLACK_WEBHOOK_URL_ACADEMY", "SLACK_WEBHOOK_URL"):
            if found.get(key):
                return found[key]
    return None


def parse_schedule(doc_id, data):
    """Firestore 문서 하나를 정규화한다. script.js 의 normalizeSchedule 과 동일한 레거시 폴백."""
    day = data.get("day")
    if day not in DAYS:
        day = "월"
    return {
        "id": doc_id,
        "day": day,
        "startTime": data.get("startTime") or data.get("time") or "",
        "endTime": data.get("endTime") or "",
        "academyType": data.get("academyType") or data.get("character") or "기타",
        "academy": data.get("academy") or data.get("title") or "이름 없는 일정",
        "managerPhone": data.get("managerPhone") or "",
        "academyPhone": data.get("academyPhone") or "",
        "academyUrl": data.get("academyUrl") or "",
        "dropoffPlace": data.get("dropoffPlace") or "",
        "memo": data.get("memo") or "",
    }


def fetch_schedules():
    """Firestore schedules 컬렉션 전체를 정규화해서 가져온다."""
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not os.path.exists(SERVICE_ACCOUNT_JSON):
        sys.exit(
            f"Firebase 서비스 계정 키를 찾을 수 없습니다: {SERVICE_ACCOUNT_JSON}\n"
            "Firebase 콘솔 > 프로젝트 설정 > 서비스 계정에서 키를 발급받아 이 경로에 두세요."
        )

    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_JSON)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    docs = db.collection(FIRESTORE_COLLECTION).stream()
    return [parse_schedule(doc.id, doc.to_dict()) for doc in docs]


def load_sample_schedules():
    with open(SAMPLE_DATA_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    return [parse_schedule(item["id"], item) for item in raw]


def schedules_for_day(schedules, day):
    items = [s for s in schedules if s["day"] == day]
    items.sort(key=lambda s: s["startTime"])
    return items


# ---------------------------------------------------------------------------
# Slack Block Kit 렌더링 — kinder-schedule/notify.py 와 동일한 관용구
# ---------------------------------------------------------------------------

def header_block(text):
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def section_mrkdwn(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def divider_block():
    return {"type": "divider"}


def context_block(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def mention_text():
    """멘션할 사람이 설정돼 있으면 '<@U123> <@U456>' 형태로 돌려준다."""
    return " ".join(f"<@{uid}>" for uid in MENTION_USER_IDS)


def app_link_block():
    return context_block(f"🔗 <{ACADEMY_APP_URL}|학원 스케줄 관리 앱 열기>")


def academy_detail_line(schedule):
    """하원도우미/학원 전화, 홈페이지, 하차장소를 값 있는 것만 한 줄로."""
    parts = []
    if schedule["managerPhone"]:
        parts.append(f"📞 하원도우미 {schedule['managerPhone']}")
    if schedule["academyPhone"]:
        parts.append(f"☎️ 학원 {schedule['academyPhone']}")
    if schedule["academyUrl"]:
        parts.append(f"🔗 {schedule['academyUrl']}")
    if schedule["dropoffPlace"]:
        parts.append(f"📍 하차: {schedule['dropoffPlace']}")
    return " · ".join(parts)


def send_to_slack(webhook_url, blocks, fallback, color=None, icon=None, name=None):
    """color 는 왼쪽 색 띠, icon·name 은 메시지 아바타와 표시 이름을 바꾼다.

    한 채널에 유치원·학원 알림이 섞여 쌓이므로 종류를 한눈에 구분하려는 것이다.
    """
    if color:
        payload = {
            "text": fallback,
            "attachments": [{"color": color, "blocks": blocks}],
        }
    else:
        payload = {"text": fallback, "blocks": blocks}

    if icon:
        payload["icon_emoji"] = icon
    if name:
        payload["username"] = name

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        # 슬랙은 거부 사유를 본문에 담아 준다(invalid_payload, channel_not_found 등).
        # 이걸 안 보여주면 원인을 찾을 수 없어 그대로 드러낸다.
        detail = e.read().decode("utf-8", "replace").strip()
        sys.exit(f"슬랙 발송 실패 (HTTP {e.code}): {detail}")


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


def send_or_print(webhook, blocks, fallback, dry_run, label,
                  color=None, icon=None, name=None):
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
    status = send_to_slack(webhook, blocks, fallback, color, icon, name)
    print(f"\n슬랙 발송 완료 (status {status})\n")
