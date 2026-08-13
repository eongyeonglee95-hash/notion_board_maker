#!/usr/bin/env python3
"""
유치원 일정 앱의 노션 DB 3개를 만든다. 처음 한 번만 실행한다.

  ① 유치원 일정   — 행사·휴원일 (휴가 필요 여부)
  ② 제출·준비물   — 마감이 있는 할 일
  ③ 급식 식단     — 날짜별 점심·간식

사용법:
  python3 apps/kinder-schedule/setup_dbs.py --parent-page <PAGE_ID> --dry-run
  python3 apps/kinder-schedule/setup_dbs.py --parent-page <PAGE_ID>

부모 페이지에 통합(정리 에이전트2)이 연결되어 있어야 한다.
노션에서 해당 페이지 > 우측 상단 ··· > 연결 > 통합 선택.

주의: 실행할 때마다 새 DB를 만든다. 이미 만들었으면 다시 돌리지 않는다.
"""

import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
NOTION_PY = os.path.join(
    REPO, ".claude", "skills", "notion-organizer", "scripts", "notion.py"
)


def load_notion():
    """notion.py 를 모듈로 불러온다. driver.py 와 같은 방식이다."""
    if not os.path.exists(NOTION_PY):
        sys.exit(f"notion.py 를 찾을 수 없습니다: {NOTION_PY}")
    spec = importlib.util.spec_from_file_location("notion_client", NOTION_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def select(*options):
    """select 속성. (이름, 색) 튜플을 받는다."""
    return {"select": {"options": [{"name": n, "color": c} for n, c in options]}}


# 담당은 두 DB 에서 같은 구성을 쓴다. 색을 맞춰야 눈에 익는다.
담당 = select(("엄마", "pink"), ("아빠", "blue"), ("미정", "gray"))


SPECS = [
    {
        "key": "유치원 일정",
        "title": "유치원 일정",
        "icon": "🏫",
        "description": "행사와 휴원일. 휴가를 내야 하는 날은 '휴가필요'를 켠다.",
        "properties": {
            "일정명": {"title": {}},
            "날짜": {"date": {}},
            "종류": select(
                ("행사", "blue"),
                ("휴원", "red"),
                ("단축수업", "orange"),
                ("상담", "purple"),
                ("기타", "gray"),
            ),
            "휴가필요": {"checkbox": {}},
            "담당": 담당,
            "메모": {"rich_text": {}},
            "출처": {"rich_text": {}},
        },
    },
    {
        "key": "제출·준비물",
        "title": "제출·준비물",
        "icon": "📄",
        "description": "마감이 있는 할 일. 담당이 '미정'이면 알림에서 눈에 띄게 표시된다.",
        "properties": {
            "항목명": {"title": {}},
            "마감일": {"date": {}},
            "종류": select(
                ("서류", "blue"),
                ("준비물", "green"),
                ("납부", "orange"),
                ("신청", "purple"),
            ),
            "완료": {"checkbox": {}},
            "담당": 담당,
            "메모": {"rich_text": {}},
            "출처": {"rich_text": {}},
        },
    },
    {
        "key": "급식 식단",
        "title": "급식 식단",
        "icon": "🍚",
        "description": "날짜별 점심과 간식. 주간 표로 보려면 웹앱을 쓴다.",
        "properties": {
            "날짜": {"title": {}},
            "일자": {"date": {}},
            "점심": {"rich_text": {}},
            "오전간식": {"rich_text": {}},
            "오후간식": {"rich_text": {}},
            "특이사항": {"rich_text": {}},
        },
    },
]


def preview():
    """만들기 전에 무엇이 생기는지 보여준다."""
    for spec in SPECS:
        print(f"\n{spec['icon']}  {spec['title']}")
        print(f"    {spec['description']}")
        for name, prop in spec["properties"].items():
            ptype = next(iter(prop))
            extra = ""
            if ptype == "select":
                names = [o["name"] for o in prop["select"]["options"]]
                extra = " → " + " / ".join(names)
            print(f"    - {name}: {ptype}{extra}")


def create(mod, parent_page):
    """DB 3개를 만들고 data_source_id 를 모은다."""
    created = {}
    for i, spec in enumerate(SPECS, 1):
        body = {
            "parent": {"type": "page_id", "page_id": parent_page},
            "title": [mod.rich_text(spec["title"])],
            "icon": {"type": "emoji", "emoji": spec["icon"]},
            "description": [mod.rich_text(spec["description"])],
            # 2025-09-03 부터 속성은 initial_data_source 아래로 들어간다
            "initial_data_source": {"properties": spec["properties"]},
        }
        db = mod.request("POST", "/databases", body)
        sources = db.get("data_sources", [])
        created[spec["key"]] = {
            "type": "database",
            "database_id": db["id"],
            "data_source_id": sources[0]["id"] if sources else None,
            "url": db.get("url", ""),
            "properties": list(spec["properties"].keys()),
        }
        print(f"  [{i}/{len(SPECS)}] {spec['icon']} {spec['title']} 생성 완료")
    return created


def main():
    parser = argparse.ArgumentParser(description="유치원 일정 앱 노션 DB 생성")
    parser.add_argument("--parent-page", help="DB 를 만들 부모 페이지 ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="만들지 않고 구성만 보여준다")
    args = parser.parse_args()

    if args.dry_run:
        print("(연습) 아래 구성으로 DB 3개를 만듭니다. 실제로 만들지는 않습니다.")
        preview()
        return

    parent = args.parent_page or os.environ.get("KINDER_PARENT_PAGE_ID")
    if not parent:
        sys.exit(
            "--parent-page <PAGE_ID> 가 필요합니다.\n"
            "  노션에서 '육아' 같은 페이지를 만들고, ··· > 연결 > 통합을 붙인 뒤\n"
            "  그 페이지 URL 끝의 32자리를 넣어주세요."
        )

    mod = load_notion()
    parent = mod._extract_id(parent)   # URL 을 통째로 붙여넣어도 되게

    print("노션에 DB 3개를 만듭니다...\n")
    try:
        created = create(mod, parent)
    except mod.NotionError as e:
        sys.exit(f"\n노션 API 오류\n{e}")

    print("\n완료. 아래 내용을 notion_targets.json 에 넣으세요:\n")
    print(json.dumps(created, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
