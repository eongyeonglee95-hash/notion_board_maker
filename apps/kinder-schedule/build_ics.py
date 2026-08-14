#!/usr/bin/env python3
"""
노션의 유치원 일정 · 제출·준비물을 구글/네이버 캘린더가 구독할 수 있는 ICS 로 만든다.

의존성 없음(표준 라이브러리만 사용). notion.py 를 옆에서 불러 쓴다.

사용법:
  python3 apps/kinder-schedule/build_ics.py > /tmp/kinder-schedule.ics

결과를 비공개 Gist 에 올려서 그 raw URL 을 캘린더 앱에 "URL로 추가"하면 구독이 된다.
GitHub Actions 에서 매일 실행해 Gist 를 갱신한다.
"""

import datetime
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
NOTION_PY = os.path.join(
    REPO, ".claude", "skills", "notion-organizer", "scripts", "notion.py"
)
TARGETS_JSON = os.path.join(REPO, "notion_targets.json")


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


def query_all(mod, data_source_id):
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


def plain(rich):
    return "".join(r.get("plain_text", "") for r in (rich or []))


def prop_text(row, name):
    prop = row.get("properties", {}).get(name, {})
    ptype = prop.get("type")
    if ptype == "title":
        return plain(prop.get("title"))
    if ptype == "rich_text":
        return plain(prop.get("rich_text"))
    return ""


def prop_date_start(row, name):
    d = row.get("properties", {}).get(name, {}).get("date")
    if not d or not d.get("start"):
        return None
    return datetime.date.fromisoformat(d["start"][:10])


def prop_checkbox(row, name):
    return bool(row.get("properties", {}).get(name, {}).get("checkbox"))


def prop_select(row, name):
    sel = row.get("properties", {}).get(name, {}).get("select")
    return sel.get("name") if sel else None


def esc(text):
    """ICS TEXT 값 이스케이프 (RFC 5545 3.3.11)."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line):
    """옥텟 75 넘으면 줄바꿈 + 선행 공백으로 접는다 (RFC 5545 3.1)."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, chunk = [], ""
    for ch in line:
        piece = (chunk + ch).encode("utf-8")
        if len(piece) > 74:
            out.append(chunk)
            chunk = ch
        else:
            chunk = chunk + ch
    out.append(chunk)
    return "\r\n ".join(out)


def vevent(uid, date, summary, description=""):
    end = date + datetime.timedelta(days=1)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}",
        f"SUMMARY:{esc(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{esc(description)}")
    lines.append("END:VEVENT")
    return [fold(l) for l in lines]


def main():
    mod = load_notion()
    targets = load_targets()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//kinder-schedule//notion-app//KO",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:유치원 일정",
        "X-WR-TIMEZONE:Asia/Seoul",
    ]

    ds_schedule = targets["유치원 일정"]["data_source_id"]
    for row in query_all(mod, ds_schedule):
        d = prop_date_start(row, "날짜")
        if not d:
            continue
        name = prop_text(row, "일정명") or "(제목 없음)"
        종류 = prop_select(row, "종류") or "기타"
        담당 = prop_select(row, "담당") or "미정"
        공휴일 = prop_checkbox(row, "공휴일")
        휴가 = prop_checkbox(row, "휴가") and not 공휴일
        icon = "🎌" if 공휴일 else ("⚠️" if 휴가 else "🏫")

        desc_parts = [f"종류: {종류}", f"담당: {담당}"]
        if 휴가:
            desc_parts.append("휴가 필요")
        if 공휴일:
            desc_parts.append("공휴일 (휴가 불필요)")

        lines += vevent(
            f"{row['id']}@kinder-schedule", d, f"{icon} {name}",
            "\n".join(desc_parts),
        )

    ds_submission = targets["제출·준비물"]["data_source_id"]
    for row in query_all(mod, ds_submission):
        d = prop_date_start(row, "마감일")
        if not d:
            continue
        name = prop_text(row, "항목명") or "(제목 없음)"
        완료 = prop_checkbox(row, "완료")
        담당 = prop_select(row, "담당") or "미정"
        icon = "✅" if 완료 else "📄"

        lines += vevent(
            f"{row['id']}@kinder-submission", d, f"{icon} {name} 마감",
            f"담당: {담당}" + (" (완료)" if 완료 else ""),
        )

    lines.append("END:VCALENDAR")
    sys.stdout.write("\r\n".join(lines) + "\r\n")


if __name__ == "__main__":
    main()
