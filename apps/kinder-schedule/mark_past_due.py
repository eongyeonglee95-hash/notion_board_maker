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


def main():
    mod = load_notion()
    targets = load_targets()
    today = datetime.date.today()

    updated = 0

    ds_schedule = targets["유치원 일정"]["data_source_id"]
    for row in query_all(mod, ds_schedule):
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
