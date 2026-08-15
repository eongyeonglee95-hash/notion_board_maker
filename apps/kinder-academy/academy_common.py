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

# 하원 몇 분 전에 알릴지. 아침 잡이 이 시각으로 슬랙 예약을 걸어둔다.
PICKUP_LEAD_MINUTES = 30

# 메시지 왼쪽 색 띠. 여러 알림이 쌓였을 때 색으로 종류를 구분한다.
COLOR_DAILY = "#f2c744"    # 학원 아침 요약 — 노랑
COLOR_IMMINENT = "#E5484D"  # 하원 임박 — 빨강(지금 움직여야 하는 것)

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


def firestore_client():
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

    return firestore.client()


def fetch_schedules():
    """Firestore schedules 컬렉션 전체를 정규화해서 가져온다."""
    docs = firestore_client().collection(FIRESTORE_COLLECTION).stream()
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


def app_button_block(text="학원 스케줄 확인하기"):
    """링크 한 줄 대신 누를 수 있는 버튼. 모바일에서 손가락으로 짚기 쉽다."""
    return {
        "type": "actions",
        "elements": [{
            "type": "button",
            "text": {"type": "plain_text", "text": text, "emoji": True},
            "url": ACADEMY_APP_URL,
        }],
    }


def kids_label():
    """'제아·유빈이가' 같은 아이 이름 문구.

    이 저장소는 공개라서 이름을 소스에 두지 않는다. GitHub Actions secret
    ACADEMY_KIDS_LABEL 로 넣고, 없으면 이름 없는 문구로 떨어진다.
    """
    return os.environ.get("ACADEMY_KIDS_LABEL", "").strip() or "아이들이"


# 학원 종류별 아이콘. 없는 종류는 🎓 로 떨어진다.
ACADEMY_ICONS = {
    "발레": "🩰",
    "무용": "🩰",
    "피아노": "🎹",
    "미술": "🎨",
    "태권도": "🥋",
    "수영": "🏊",
    "축구": "⚽",
    "영어": "🔤",
    "수학": "🔢",
    "독서": "📚",
    "체육": "🤸",
}

_CLOCK_HOUR = ["🕛", "🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚"]
_CLOCK_HALF = ["🕧", "🕜", "🕝", "🕞", "🕟", "🕠", "🕡", "🕢", "🕣", "🕤", "🕥", "🕦"]


def clock_emoji(hhmm):
    """'18:42' → 🕡 처럼 30분 단위로 내림한 시계 아이콘."""
    try:
        h, m = (int(x) for x in hhmm.split(":")[:2])
    except (ValueError, AttributeError):
        return "🕐"
    faces = _CLOCK_HALF if m >= 30 else _CLOCK_HOUR
    return faces[h % 12]


def academy_row(schedule):
    """'🩰 라푸앙트 발레' 형태의 학원 줄. 종류가 없으면 이름만."""
    kind = schedule["academyType"]
    icon = ACADEMY_ICONS.get(kind, "🎓")
    if kind and kind != "기타":
        return f"{icon} {schedule['academy']} {kind}"
    return f"{icon} {schedule['academy']}"


def pickup_rows(schedule):
    """하원도우미·하차위치를 값 있는 것만 각각 한 줄로.

    학원 전화·홈페이지는 급할 때 볼 정보가 아니라서 슬랙에는 싣지 않는다
    (필요하면 앱 링크로 들어가서 본다).
    """
    rows = []
    if schedule["dropoffPlace"]:
        rows.append(f"📍 {schedule['dropoffPlace']}")
    if schedule["managerPhone"]:
        rows.append(f"📞 하원도우미 {schedule['managerPhone']}")
    return rows


# ---------------------------------------------------------------------------
# 슬랙 Web API — 예약 발송용
#
# 웹훅으로는 "지금" 밖에 못 보낸다. 하원 30분 전이라는 정확한 시각에 알리려면
# 크론이 그 시각에 깨어나야 하는데, GitHub Actions 크론은 20~50분씩 밀린다.
# 그래서 아침 잡이 한 번 돌면서 chat.scheduleMessage 로 예약만 걸어두고,
# 실제 발송 시각은 슬랙 서버가 지킨다.
# ---------------------------------------------------------------------------

SLACK_API_BASE = "https://slack.com/api/"


def load_bot_token():
    """예약 발송용 봇 토큰(xoxb-). 없으면 None → 웹훅 방식으로 떨어진다."""
    return os.environ.get("SLACK_BOT_TOKEN_ACADEMY", "").strip() or None


def load_channel():
    """봇이 글을 올릴 채널. 채널 ID(C...) 또는 #이름 둘 다 된다."""
    return os.environ.get("SLACK_CHANNEL_ACADEMY", "").strip() or None


def slack_api(method, token, payload):
    """슬랙 Web API 호출. 슬랙은 실패해도 HTTP 200 에 ok:false 로 답하므로 직접 본다."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SLACK_API_BASE + method, data=body, method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").strip()
        sys.exit(f"슬랙 API {method} 실패 (HTTP {e.code}): {detail}")

    if not data.get("ok"):
        sys.exit(f"슬랙 API {method} 실패: {data.get('error')} — {data}")
    return data


def message_payload(channel, blocks, fallback, color=None, icon=None, name=None):
    payload = {"channel": channel, "text": fallback}
    if color:
        payload["attachments"] = [{"color": color, "blocks": blocks}]
    else:
        payload["blocks"] = blocks
    if icon:
        payload["icon_emoji"] = icon
    if name:
        payload["username"] = name
    return payload


def post_message(token, channel, blocks, fallback, color=None, icon=None, name=None):
    return slack_api("chat.postMessage", token,
                     message_payload(channel, blocks, fallback, color, icon, name))


def schedule_message(token, channel, post_at, blocks, fallback,
                     color=None, icon=None, name=None):
    """post_at(epoch 초)에 슬랙이 대신 보내도록 예약한다."""
    payload = message_payload(channel, blocks, fallback, color, icon, name)
    payload["post_at"] = int(post_at)
    return slack_api("chat.scheduleMessage", token, payload)


def clear_scheduled(token, channel, oldest, latest):
    """구간 안의 기존 예약을 지운다. 아침 잡을 두 번 돌려도 중복 예약이 안 남는다."""
    data = slack_api("chat.scheduledMessages.list", token, {
        "channel": channel, "oldest": int(oldest), "latest": int(latest), "limit": 100,
    })
    removed = 0
    for m in data.get("scheduled_messages", []):
        slack_api("chat.deleteScheduledMessage", token, {
            "channel": channel, "scheduled_message_id": m["id"],
        })
        removed += 1
    return removed


def build_pickup_blocks(schedule, lead_minutes=PICKUP_LEAD_MINUTES):
    """하원 임박 알림 본문. 슬랙에서 글자를 키울 수 있는 블록은 header 뿐이라,
    제목은 굵게 한 번만 쓰고 정작 급할 때 봐야 하는 하원 시간을 header 로 올린다."""
    blocks = [
        section_mrkdwn(
            f"*🚨 하원 {lead_minutes}분 전*\n{kids_label()} 곧 도착해요. 지금 준비해 주세요!"
        ),
        header_block(f"{clock_emoji(schedule['endTime'])} {schedule['endTime']} 하원"),
        section_mrkdwn("\n".join([academy_row(schedule)] + pickup_rows(schedule))),
    ]

    mentions = mention_text()
    if mentions:
        blocks.append(section_mrkdwn(mentions))

    blocks.append(app_button_block())
    fallback = f"하원 {lead_minutes}분 전 · {schedule['endTime']} · {schedule['academy']}"
    return blocks, fallback


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
        elif t == "actions":
            print("  " + " ".join(f"[{e['text']['text']}]" for e in b["elements"]))


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
