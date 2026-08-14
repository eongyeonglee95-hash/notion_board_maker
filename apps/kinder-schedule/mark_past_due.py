#!/usr/bin/env python3
"""
노션의 유치원 일정 · 제출·준비물 에서 날짜가 지난 항목의 제목에 취소선을 긋는다.

노션에는 날짜 기준 조건부 서식이 없어서, 이 스크립트가 매일 실행되며
대신 그 역할을 한다 (notify.py 와 함께 GitHub Actions 에서 매일 아침 실행됨).

의존성 없음(표준 라이브러리만 사용). notion.py 를 옆에서 불러 쓴다.

사용법:
  python3 apps/kinder-schedule/mark_past_due.py
"""

import datetime
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
NOTION_PY = os.path.join(
    REPO, ".claude", "skills", "notion-organizer", "scripts", "notion.py"
)
TARGETS_JSON = os.path.join(REPO, "notion_targets.json")

# 관공서 공휴일(대체공휴일 포함). 근로자의날(5/1)은 관공서 공휴일이 아니라서 뺀다.
# 매년 발표되는 달력을 보고 다음 해가 추가돼야 한다.
KR_HOLIDAYS = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01",
    "2026-03-02", "2026-05-05", "2026-05-24", "2026-05-25", "2026-06-03",
    "2026-06-06", "2026-07-17", "2026-08-15", "2026-08-17", "2026-09-24",
    "2026-09-25", "2026-09-26", "2026-10-03", "2026-10-05", "2026-10-09",
    "2026-12-25",
    "2027-01-01", "2027-02-06", "2027-02-07", "2027-02-08", "2027-02-09",
    "2027-03-01", "2027-05-05", "2027-05-13", "2027-06-06", "2027-07-17",
    "2027-07-19", "2027-08-15", "2027-08-16", "2027-09-14", "2027-09-15",
    "2027-09-16", "2027-10-03", "2027-10-04", "2027-10-09", "2027-10-11",
    "2027-12-25", "2027-12-27",
}


def load_notion():
    if not os.path.exists(NOTION_PY):
        sys.exit(f"notion.py 를 찾을 수 없습니다: {NOTION_PY}")
    spec = importlib.util.spec_from_file_location("notion_client", NOTION_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_targets():
    import json
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


def title_text_and_strike(row, name):
    """제목 속성의 현재 텍스트와 취소선 여부를 돌려준다."""
    prop = row.get("properties", {}).get(name, {})
    parts = prop.get("title", [])
    text = "".join(p.get("plain_text", "") for p in parts)
    struck = bool(parts) and all(
        p.get("annotations", {}).get("strikethrough") for p in parts
    )
    return text, struck


def end_date(row, name):
    """날짜 속성의 end(없으면 start)를 date 객체로 돌려준다. 값이 없으면 None."""
    d = row.get("properties", {}).get(name, {}).get("date")
    if not d:
        return None
    raw = d.get("end") or d.get("start")
    if not raw:
        return None
    return datetime.date.fromisoformat(raw[:10])


def strike_title(mod, page_id, prop_name, text):
    mod.request("PATCH", f"/pages/{page_id}", {
        "properties": {
            prop_name: {
                "title": [{
                    "text": {"content": text},
                    "annotations": {"strikethrough": True},
                }]
            }
        },
    })


def mark_holiday(mod, page_id):
    mod.request("PATCH", f"/pages/{page_id}", {
        "properties": {"공휴일": {"checkbox": True}},
    })


def main():
    mod = load_notion()
    targets = load_targets()
    today = datetime.date.today()

    updated = 0

    ds_schedule = targets["유치원 일정"]["data_source_id"]
    schedule_rows = query_all(mod, ds_schedule)

    for row in schedule_rows:
        start = row.get("properties", {}).get("날짜", {}).get("date", {})
        start = (start or {}).get("start")
        if not start or row["properties"].get("공휴일", {}).get("checkbox"):
            continue
        if start[:10] in KR_HOLIDAYS:
            mark_holiday(mod, row["id"])
            name, _ = title_text_and_strike(row, "일정명")
            print(f"공휴일 표시: {name} ({start[:10]})")
            updated += 1
            time.sleep(0.34)

    for row in schedule_rows:
        d = end_date(row, "날짜")
        if not d or d >= today:
            continue
        text, struck = title_text_and_strike(row, "일정명")
        if not text or struck:
            continue
        strike_title(mod, row["id"], "일정명", text)
        print(f"취소선(일정): {text}")
        updated += 1
        time.sleep(0.34)

    ds_submission = targets["제출·준비물"]["data_source_id"]
    for row in query_all(mod, ds_submission):
        d = end_date(row, "마감일")
        if not d or d >= today:
            continue
        text, struck = title_text_and_strike(row, "항목명")
        if not text or struck:
            continue
        strike_title(mod, row["id"], "항목명", text)
        print(f"취소선(준비물): {text}")
        updated += 1
        time.sleep(0.34)

    print(f"[{today}] 완료: {updated}건에 취소선 적용")


if __name__ == "__main__":
    main()
