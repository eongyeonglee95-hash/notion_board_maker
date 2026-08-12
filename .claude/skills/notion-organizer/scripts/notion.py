#!/usr/bin/env python3
"""
노션 API 클라이언트 (Notion-Version: 2025-09-03)

외부 패키지 설치가 필요 없습니다. 파이썬 표준 라이브러리만 사용합니다.

2025-09-03 버전부터 노션 API 구조가 바뀌었습니다:
  - 데이터베이스(database)는 껍데기이고, 실제 행과 속성은 데이터소스(data source)에 들어갑니다.
  - DB 생성 시 속성은 initial_data_source.properties 아래에 넣습니다.
  - 행(페이지) 생성 시 parent 는 database_id 가 아니라 data_source_id 를 씁니다.

사용법:
  python3 notion.py whoami
  python3 notion.py search [검색어] [--type page|data_source]
  python3 notion.py create-db --parent-page <page_id> --spec spec.json
  python3 notion.py add-rows --data-source <ds_id> --rows rows.json
  python3 notion.py create-page --parent-page <page_id> --spec page.json
  python3 notion.py append-blocks --block <page_id> --blocks blocks.json
  python3 notion.py get-db --database <db_id>
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"

# 노션 API 제한값
MAX_BLOCKS_PER_REQUEST = 100      # 한 요청에 붙일 수 있는 블록 수
MAX_RICH_TEXT_LENGTH = 2000       # 리치 텍스트 한 조각의 최대 길이
REQUEST_INTERVAL = 0.34           # 초당 3회 제한을 지키기 위한 간격


class NotionError(Exception):
    """노션 API 가 에러를 돌려줬을 때 발생합니다."""


SETUP_GUIDE = (
    "  1) https://www.notion.so/profile/integrations 에서 통합(Integration)을 만들고\n"
    "  2) Configuration 탭 > Internal Integration Secret 의 Show > Copy 를 눌러 복사한 뒤\n"
    "  3) 프로젝트 루트의 .env 파일에 아래처럼 넣어주세요:\n"
    "     NOTION_TOKEN=ntn_로시작하는_실제토큰"
)


def _validate_token(token):
    """토큰이 실제로 쓸 수 있는 값인지 확인합니다."""
    token = (token or "").strip().strip('"').strip("'")

    if not token:
        sys.exit(f"노션 토큰이 비어 있습니다.\n{SETUP_GUIDE}")

    # .env.example 의 안내 문구가 그대로 남아 있는 경우
    if "여기에" in token or "붙여넣" in token or token in ("ntn_", "your_token"):
        sys.exit(
            "아직 .env 에 실제 토큰이 들어가지 않았습니다. 안내 문구가 그대로 남아 있습니다.\n"
            f"{SETUP_GUIDE}"
        )

    # HTTP 헤더에는 ASCII 만 들어갈 수 있습니다 (한글이 섞이면 전송 자체가 불가)
    try:
        token.encode("ascii")
    except UnicodeEncodeError:
        sys.exit(
            "토큰에 한글 등 ASCII 가 아닌 문자가 섞여 있습니다.\n"
            "설명 문구를 지우고 토큰만 남겨주세요.\n"
            f"{SETUP_GUIDE}"
        )

    if not token.startswith(("ntn_", "secret_")):
        sys.exit(
            f"토큰 형식이 올바르지 않습니다 (현재 값이 '{token[:6]}...' 로 시작).\n"
            "노션 토큰은 ntn_ 으로 시작합니다.\n"
            f"{SETUP_GUIDE}"
        )

    return token


def load_token():
    """환경변수 또는 .env 파일에서 노션 토큰을 읽습니다."""
    token = os.environ.get("NOTION_TOKEN")
    if token:
        return _validate_token(token)

    # 프로젝트 루트의 .env 를 위로 올라가며 찾습니다
    here = os.path.abspath(__file__)
    for _ in range(6):
        here = os.path.dirname(here)
        env_path = os.path.join(here, ".env")
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    if key.strip() == "NOTION_TOKEN":
                        return _validate_token(value)

    sys.exit(f"노션 토큰을 찾을 수 없습니다.\n{SETUP_GUIDE}")


def request(method, path, body=None, token=None):
    """노션 API 를 호출하고 결과를 dict 로 돌려줍니다."""
    token = token or load_token()
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
            code = payload.get("code", "")
            message = payload.get("message", raw)
        except json.JSONDecodeError:
            code, message = "", raw
        raise NotionError(_friendly_error(e.code, code, message)) from None
    except urllib.error.URLError as e:
        raise NotionError(f"네트워크 연결에 실패했습니다: {e.reason}") from None


def _friendly_error(status, code, message):
    """노션 에러를 사람이 읽을 수 있는 한국어 안내로 바꿉니다."""
    hints = {
        "unauthorized": "토큰이 잘못되었거나 만료되었습니다. .env 의 NOTION_TOKEN 을 다시 확인해주세요.",
        "restricted_resource": "통합에 권한이 없습니다. 노션에서 해당 페이지 우측 상단 ··· > 연결 > 통합 이름을 선택해 연결해주세요.",
        "object_not_found": (
            "해당 ID를 찾을 수 없습니다. ID가 맞는지, 그리고 그 페이지에 통합이 연결되어 있는지 확인해주세요.\n"
            "  (노션에서 페이지 > ··· > 연결 > 통합 선택)"
        ),
        "validation_error": "요청 형식이 잘못되었습니다. 아래 원문 메시지를 확인해주세요.",
        "rate_limited": "요청이 너무 빠릅니다. 잠시 후 다시 시도해주세요.",
    }
    hint = hints.get(code, "")
    parts = [f"[{status} {code}] {message}"]
    if hint:
        parts.append(f"→ {hint}")
    return "\n".join(parts)


def rich_text(content, bold=False, code=False, color="default", link=None):
    """문자열을 노션 리치 텍스트 조각으로 만듭니다. 2000자를 넘으면 잘라냅니다."""
    content = str(content)
    if len(content) > MAX_RICH_TEXT_LENGTH:
        content = content[: MAX_RICH_TEXT_LENGTH - 1] + "…"
    item = {
        "type": "text",
        "text": {"content": content},
        "annotations": {"bold": bold, "code": code, "color": color},
    }
    if link:
        item["text"]["link"] = {"url": link}
    return item


def chunked(items, size):
    """리스트를 size 개씩 잘라서 돌려줍니다."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ---------------------------------------------------------------- 명령어 구현


def cmd_whoami(args):
    """토큰이 살아있는지, 어떤 통합인지 확인합니다."""
    me = request("GET", "/users/me")
    name = me.get("name") or me.get("bot", {}).get("owner", {}).get("type", "이름 없음")
    print(f"연결 성공: {name} (id: {me.get('id')})")
    print(f"API 버전: {NOTION_VERSION}")
    return me


def cmd_search(args):
    """통합이 접근할 수 있는 페이지/데이터소스를 찾습니다."""
    body = {"page_size": 50}
    if args.query:
        body["query"] = args.query
    if args.type:
        body["filter"] = {"property": "object", "value": args.type}

    result = request("POST", "/search", body)
    results = result.get("results", [])
    if not results:
        print(
            "접근 가능한 항목이 없습니다.\n"
            "노션에서 정리할 페이지를 열고 우측 상단 ··· > 연결 > 통합을 선택해 연결해주세요."
        )
        return result

    for item in results:
        obj = item.get("object")
        title = _extract_title(item)
        print(f"{obj:12} {item['id']}  {title}")
    return result


def _extract_title(item):
    """페이지/데이터소스 객체에서 제목 문자열을 뽑아냅니다."""
    if item.get("object") in ("database", "data_source"):
        parts = item.get("title", [])
    else:
        props = item.get("properties", {})
        parts = []
        for prop in props.values():
            if prop.get("type") == "title":
                parts = prop.get("title", [])
                break
    return "".join(p.get("plain_text", "") for p in parts) or "(제목 없음)"


def cmd_create_db(args):
    """
    데이터베이스를 만듭니다.

    spec.json 형식:
      {
        "title": "AI 개발도구",
        "icon": "🛠️",
        "description": "선택 사항",
        "properties": {
          "도구명": {"title": {}},
          "카테고리": {"select": {"options": [{"name": "코딩", "color": "blue"}]}}
        }
      }
    """
    spec = json.load(open(args.spec, encoding="utf-8"))

    body = {
        "parent": {"type": "page_id", "page_id": args.parent_page},
        "title": [rich_text(spec["title"])],
        # 2025-09-03 부터 속성은 initial_data_source 아래로 들어갑니다
        "initial_data_source": {"properties": spec["properties"]},
    }
    if spec.get("icon"):
        body["icon"] = {"type": "emoji", "emoji": spec["icon"]}
    if spec.get("description"):
        body["description"] = [rich_text(spec["description"])]

    db = request("POST", "/databases", body)

    data_sources = db.get("data_sources", [])
    ds_id = data_sources[0]["id"] if data_sources else None

    print(json.dumps({
        "database_id": db["id"],
        "data_source_id": ds_id,
        "url": db.get("url", ""),
    }, ensure_ascii=False, indent=2))
    return db


def cmd_add_rows(args):
    """
    데이터소스에 행(페이지)을 추가합니다.

    rows.json 형식:
      [
        {
          "icon": "🤖",
          "properties": {"도구명": {"title": [{"text": {"content": "Claude Code"}}]}},
          "children": [ ...블록... ]
        }
      ]
    """
    rows = json.load(open(args.rows, encoding="utf-8"))
    created = []

    for i, row in enumerate(rows, 1):
        body = {
            # 2025-09-03 부터 부모는 database_id 가 아니라 data_source_id 입니다
            "parent": {"type": "data_source_id", "data_source_id": args.data_source},
            "properties": row["properties"],
        }
        if row.get("icon"):
            body["icon"] = {"type": "emoji", "emoji": row["icon"]}

        children = row.get("children", [])
        # 페이지 생성 시에는 최대 100개까지만 함께 보낼 수 있습니다
        body["children"] = children[:MAX_BLOCKS_PER_REQUEST]

        page = request("POST", "/pages", body)
        created.append(page["id"])

        # 100개를 넘는 블록은 나눠서 이어붙입니다
        for batch in chunked(children[MAX_BLOCKS_PER_REQUEST:], MAX_BLOCKS_PER_REQUEST):
            time.sleep(REQUEST_INTERVAL)
            request("PATCH", f"/blocks/{page['id']}/children", {"children": batch})

        print(f"  [{i}/{len(rows)}] 생성 완료")
        time.sleep(REQUEST_INTERVAL)

    print(json.dumps({"created": len(created), "page_ids": created},
                     ensure_ascii=False, indent=2))
    return created


def cmd_create_page(args):
    """
    일반 페이지(데이터베이스가 아닌)를 만듭니다.

    page.json 형식:
      {"title": "제목", "icon": "📚", "children": [ ...블록... ]}
    """
    spec = json.load(open(args.spec, encoding="utf-8"))
    children = spec.get("children", [])

    body = {
        "parent": {"type": "page_id", "page_id": args.parent_page},
        "properties": {"title": {"title": [rich_text(spec["title"])]}},
        "children": children[:MAX_BLOCKS_PER_REQUEST],
    }
    if spec.get("icon"):
        body["icon"] = {"type": "emoji", "emoji": spec["icon"]}

    page = request("POST", "/pages", body)

    for batch in chunked(children[MAX_BLOCKS_PER_REQUEST:], MAX_BLOCKS_PER_REQUEST):
        time.sleep(REQUEST_INTERVAL)
        request("PATCH", f"/blocks/{page['id']}/children", {"children": batch})

    print(json.dumps({"page_id": page["id"], "url": page.get("url", "")},
                     ensure_ascii=False, indent=2))
    return page


def cmd_append_blocks(args):
    """이미 있는 페이지 아래에 블록을 이어붙입니다."""
    blocks = json.load(open(args.blocks, encoding="utf-8"))
    if isinstance(blocks, dict):
        blocks = blocks.get("children", [])

    for batch in chunked(blocks, MAX_BLOCKS_PER_REQUEST):
        request("PATCH", f"/blocks/{args.block}/children", {"children": batch})
        time.sleep(REQUEST_INTERVAL)

    print(f"블록 {len(blocks)}개 추가 완료")


def cmd_get_db(args):
    """데이터베이스 정보와 데이터소스 ID를 확인합니다."""
    db = request("GET", f"/databases/{args.database}")
    print(json.dumps({
        "title": _extract_title(db),
        "database_id": db["id"],
        "data_sources": db.get("data_sources", []),
        "url": db.get("url", ""),
    }, ensure_ascii=False, indent=2))
    return db


TEMPLATE_PLACEHOLDERS = (
    "주요 개념", "핵심 키워드", "중요 공식", "이론", "질문", "추가조사",
    "할일", "과제", "강의 노트",
)


def _looks_empty(page_id):
    """
    페이지가 정말 비어 있는지 확인합니다.

    제목·속성·본문에 실질 내용이 없고 템플릿 문구만 있으면 비었다고 봅니다.
    삭제 전에 반드시 이 검사를 통과해야 합니다.
    """
    page = request("GET", f"/pages/{page_id}")
    reasons = []

    # 1) 제목 외의 속성에 값이 있는지
    for name, prop in page.get("properties", {}).items():
        ptype = prop.get("type")
        if ptype == "title":
            continue
        value = _simplify_value(prop)
        if value not in (None, "", [], {}):
            # 날짜와 select 는 템플릿에도 들어있을 수 있어 내용으로 치지 않습니다
            if ptype not in ("date", "select", "created_time", "last_edited_time",
                             "created_by", "last_edited_by"):
                reasons.append(f"{name}={value!r}")

    # 2) 본문에 템플릿 문구가 아닌 텍스트가 있는지
    time.sleep(REQUEST_INTERVAL)
    data = request("GET", f"/blocks/{page_id}/children?page_size=100")
    for block in data.get("results", []):
        btype = block.get("type", "")
        if btype in ("child_page", "child_database"):
            reasons.append(f"하위 {btype} 있음")
            continue
        if btype in ("image", "file", "video", "pdf", "bookmark", "embed"):
            reasons.append(f"첨부({btype}) 있음")
            continue
        text = _plain((block.get(btype) or {}).get("rich_text")).strip()
        if not text:
            continue
        # 템플릿 문구인지 확인 (콜론 앞부분만 남은 빈 항목)
        stripped = text.rstrip(":： ").strip()
        if any(ph in stripped for ph in TEMPLATE_PLACEHOLDERS) and len(stripped) < 30:
            continue
        reasons.append(f"본문: {text[:40]!r}")

    return (len(reasons) == 0), reasons


def cmd_trash_pages(args):
    """
    페이지(DB 행 포함)를 휴지통으로 보냅니다.

    --ids-file 에 한 줄에 하나씩 페이지 ID 를 적습니다.
    기본적으로 '정말 비어 있는지' 검사해서 통과한 것만 지웁니다.
    내용이 있으면 건너뛰고 이유를 출력합니다.
    """
    with open(args.ids_file, encoding="utf-8") as f:
        ids = [line.strip() for line in f
               if line.strip() and not line.strip().startswith("#")]

    trashed, skipped = [], []
    for i, page_id in enumerate(ids, 1):
        title = ""
        try:
            page = request("GET", f"/pages/{page_id}")
            title = _extract_title(page)
        except NotionError as e:
            print(f"[{i}/{len(ids)}] {page_id} 조회 실패 — 건너뜀\n    {e}")
            skipped.append((page_id, "조회 실패"))
            continue

        if not args.force:
            time.sleep(REQUEST_INTERVAL)
            empty, reasons = _looks_empty(page_id)
            if not empty:
                print(f"[{i}/{len(ids)}] '{title}' 내용이 있어 건너뜀")
                for r in reasons[:3]:
                    print(f"    - {r}")
                skipped.append((page_id, "; ".join(reasons[:3])))
                time.sleep(REQUEST_INTERVAL)
                continue

        if args.dry_run:
            print(f"[{i}/{len(ids)}] (연습) '{title}' 삭제 대상")
            trashed.append(page_id)
        else:
            request("PATCH", f"/pages/{page_id}", {"in_trash": True})
            print(f"[{i}/{len(ids)}] '{title}' 휴지통으로 이동")
            trashed.append(page_id)
        time.sleep(REQUEST_INTERVAL)

    print(f"\n{'(연습) ' if args.dry_run else ''}삭제 {len(trashed)}건, 건너뜀 {len(skipped)}건")
    if not args.dry_run and trashed:
        print("노션 좌측 하단 휴지통에서 30일 안에 복구할 수 있습니다.")
    return trashed


def cmd_replace_blocks(args):
    """
    페이지의 본문 블록을 새 내용으로 교체합니다.

    하위 페이지(child_page)와 하위 데이터베이스(child_database)는 절대 지우지 않습니다.
    그것들을 지우면 안에 든 내용까지 통째로 휴지통으로 가기 때문입니다.
    """
    removable, protected = [], []
    cursor = None
    while True:
        path = f"/blocks/{args.block}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        data = request("GET", path)
        for block in data.get("results", []):
            if block.get("type") in ("child_page", "child_database"):
                protected.append(block)
            else:
                removable.append(block["id"])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        time.sleep(REQUEST_INTERVAL)

    if protected:
        names = [
            (b.get(b["type"], {}) or {}).get("title", "(제목 없음)") for b in protected
        ]
        print(f"보호됨 (삭제하지 않음): {', '.join(names)}")

    for block_id in removable:
        request("DELETE", f"/blocks/{block_id}")
        time.sleep(REQUEST_INTERVAL)

    blocks = json.load(open(args.blocks, encoding="utf-8"))
    if isinstance(blocks, dict):
        blocks = blocks.get("children", [])

    for batch in chunked(blocks, MAX_BLOCKS_PER_REQUEST):
        request("PATCH", f"/blocks/{args.block}/children", {"children": batch})
        time.sleep(REQUEST_INTERVAL)

    print(f"블록 {len(removable)}개를 지우고 {len(blocks)}개로 교체했습니다.")
    if protected:
        print("하위 페이지/DB 는 그대로 있으며, 교체한 본문 아래로 밀려납니다.")


def cmd_get_page(args):
    """페이지 하나의 속성을 조회합니다."""
    page = request("GET", f"/pages/{args.page}")
    print(json.dumps({
        "title": _extract_title(page),
        "id": page["id"],
        "parent": page.get("parent", {}),
        "properties": page.get("properties", {}),
        "url": page.get("url", ""),
    }, ensure_ascii=False, indent=2))
    return page


def _plain(rich):
    """리치 텍스트 배열에서 순수 문자열만 뽑습니다."""
    return "".join(r.get("plain_text", "") for r in (rich or []))


def _block_to_text(block, depth=0):
    """블록 하나를 읽기 쉬운 텍스트 줄로 바꿉니다."""
    btype = block.get("type", "")
    body = block.get(btype, {}) or {}
    indent = "  " * depth
    text = _plain(body.get("rich_text"))

    markers = {
        "heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
        "bulleted_list_item": "- ", "numbered_list_item": "1. ",
        "quote": "> ", "toggle": "▸ ", "callout": "💬 ",
    }
    if btype in markers:
        return f"{indent}{markers[btype]}{text}"
    if btype == "to_do":
        mark = "x" if body.get("checked") else " "
        return f"{indent}- [{mark}] {text}"
    if btype == "code":
        lang = body.get("language", "")
        return f"{indent}```{lang}\n{text}\n{indent}```"
    if btype == "divider":
        return f"{indent}---"
    if btype == "table_row":
        cells = [_plain(c) for c in body.get("cells", [])]
        return f"{indent}| " + " | ".join(cells) + " |"
    if btype in ("child_page", "child_database"):
        kind = "페이지" if btype == "child_page" else "DB"
        return f"{indent}[{kind}] {body.get('title', '')}  (id: {block['id']})"
    if btype == "table":
        return f"{indent}[표 {body.get('table_width', '?')}열]"
    if text:
        return f"{indent}{text}"
    return f"{indent}({btype})"


def _fetch_blocks(block_id, depth, max_depth, lines):
    """블록을 재귀적으로 읽어 텍스트 줄 목록에 담습니다."""
    cursor = None
    while True:
        path = f"/blocks/{block_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        data = request("GET", path)

        for block in data.get("results", []):
            lines.append(_block_to_text(block, depth))
            # 자식이 있고 깊이가 남았으면 더 파고듭니다
            if block.get("has_children") and depth < max_depth:
                if block.get("type") != "child_page":  # 하위 페이지 본문은 따로 조회
                    time.sleep(REQUEST_INTERVAL)
                    _fetch_blocks(block["id"], depth + 1, max_depth, lines)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        time.sleep(REQUEST_INTERVAL)


def cmd_get_blocks(args):
    """페이지 본문을 마크다운 비슷한 텍스트로 읽어옵니다."""
    lines = []
    _fetch_blocks(args.block, 0, args.depth, lines)
    print("\n".join(lines) if lines else "(본문이 비어 있습니다)")
    return lines


def cmd_query(args):
    """데이터소스의 행을 모두 조회합니다."""
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = request("POST", f"/data_sources/{args.data_source}/query", body)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        time.sleep(REQUEST_INTERVAL)

    simplified = []
    for row in rows:
        item = {"id": row["id"], "properties": {}}
        for name, prop in row.get("properties", {}).items():
            item["properties"][name] = _simplify_value(prop)
        simplified.append(item)

    print(json.dumps({"count": len(simplified), "rows": simplified},
                     ensure_ascii=False, indent=2))
    return simplified


def _simplify_value(prop):
    """속성 값을 읽기 쉬운 형태로 줄입니다."""
    ptype = prop.get("type")
    value = prop.get(ptype)
    if ptype in ("title", "rich_text"):
        return _plain(value)
    if ptype == "select":
        return value.get("name") if value else None
    if ptype == "status":
        return value.get("name") if value else None
    if ptype == "multi_select":
        return [v.get("name") for v in value or []]
    if ptype == "date":
        return value.get("start") if value else None
    if ptype == "people":
        return [v.get("name") for v in value or []]
    if ptype == "relation":
        return [v.get("id") for v in value or []]
    if ptype == "files":
        return [v.get("name") for v in value or []]
    return value


def cmd_inspect(args):
    """
    URL 이나 ID 를 받아 그것이 페이지인지 데이터베이스인지 판별하고 구조를 보여줍니다.
    무엇부터 봐야 할지 모를 때 가장 먼저 쓰는 명령입니다.
    """
    target = _extract_id(args.target)
    print(f"대상 ID: {target}\n")

    # 데이터베이스인지 먼저 확인합니다
    try:
        db = request("GET", f"/databases/{target}")
        print(f"종류: 데이터베이스")
        print(f"제목: {_extract_title(db)}")
        print(f"부모: {db.get('parent', {})}")
        print("\n데이터소스:")
        for ds in db.get("data_sources", []):
            print(f"  - {ds.get('name')}  (id: {ds.get('id')})")

        for ds in db.get("data_sources", []):
            detail = request("GET", f"/data_sources/{ds['id']}")
            print(f"\n[{ds.get('name')}] 속성:")
            for name, prop in detail.get("properties", {}).items():
                ptype = prop.get("type")
                extra = ""
                if ptype in ("select", "multi_select", "status"):
                    opts = (prop.get(ptype) or {}).get("options", [])
                    extra = " → " + ", ".join(
                        f"{o['name']}({o.get('color','')})" for o in opts
                    )
                print(f"  {name}: {ptype}{extra}")
        return db
    except NotionError:
        pass

    # 데이터베이스가 아니면 페이지로 조회합니다
    page = request("GET", f"/pages/{target}")
    print(f"종류: 페이지")
    print(f"제목: {_extract_title(page)}")
    print(f"부모: {page.get('parent', {})}")
    print(f"URL: {page.get('url', '')}")
    return page


_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX32_AT_END_RE = re.compile(r"([0-9a-fA-F]{32})$")
_HEX32_RE = re.compile(r"[0-9a-fA-F]{32}")


def _extract_id(value):
    """
    노션 URL 이나 ID 에서 32자리 ID 를 뽑아냅니다. ?v= 뒤의 뷰 ID 는 무시합니다.

    노션 URL 은 제목 뒤에 ID 가 붙는 형태(.../제목-32자리)이므로, 마지막 경로
    조각의 '끝' 에서 찾아야 합니다. URL 전체에서 하이픈을 지우고 찾으면
    제목의 끝글자가 16진수일 때 ID 가 앞으로 밀립니다.
      - .../Cafe-<ID>            → "Cafe" 가 전부 16진수
      - .../%EB%94%94-<ID>       → 한글 제목이 퍼센트 인코딩되면 끝이 "94"
    """
    value = (value or "").strip()
    text = value.split("?")[0].split("#")[0]

    segments = [s for s in text.split("/") if s]
    target = segments[-1] if segments else text

    match = _UUID_RE.search(target)          # 하이픈이 들어간 UUID 형태
    if match:
        return match.group(0).replace("-", "")

    match = _HEX32_AT_END_RE.search(target)  # 노션 URL 은 ID 가 항상 끝에 온다
    if match:
        return match.group(1)

    matches = _HEX32_RE.findall(target)      # 그래도 못 찾으면 마지막 후보
    return matches[-1] if matches else value


def main():
    parser = argparse.ArgumentParser(description="노션 API 클라이언트")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami", help="토큰 연결 확인")

    p_search = sub.add_parser("search", help="접근 가능한 페이지/DB 검색")
    p_search.add_argument("query", nargs="?", default="")
    p_search.add_argument("--type", choices=["page", "data_source"])

    p_db = sub.add_parser("create-db", help="데이터베이스 생성")
    p_db.add_argument("--parent-page", required=True)
    p_db.add_argument("--spec", required=True)

    p_rows = sub.add_parser("add-rows", help="데이터소스에 행 추가")
    p_rows.add_argument("--data-source", required=True)
    p_rows.add_argument("--rows", required=True)

    p_page = sub.add_parser("create-page", help="일반 페이지 생성")
    p_page.add_argument("--parent-page", required=True)
    p_page.add_argument("--spec", required=True)

    p_blocks = sub.add_parser("append-blocks", help="페이지에 블록 추가")
    p_blocks.add_argument("--block", required=True)
    p_blocks.add_argument("--blocks", required=True)

    p_get = sub.add_parser("get-db", help="DB 정보 조회")
    p_get.add_argument("--database", required=True)

    p_inspect = sub.add_parser("inspect", help="URL/ID가 페이지인지 DB인지 판별하고 구조 표시")
    p_inspect.add_argument("target", help="노션 URL 또는 ID")

    p_gp = sub.add_parser("get-page", help="페이지 속성 조회")
    p_gp.add_argument("--page", required=True)

    p_gb = sub.add_parser("get-blocks", help="페이지 본문을 텍스트로 읽기")
    p_gb.add_argument("--block", required=True)
    p_gb.add_argument("--depth", type=int, default=2, help="중첩 탐색 깊이 (기본 2)")

    p_q = sub.add_parser("query", help="데이터소스의 행 전체 조회")
    p_q.add_argument("--data-source", required=True)

    p_rb = sub.add_parser("replace-blocks",
                          help="페이지 본문 교체 (하위 페이지/DB 는 보호)")
    p_rb.add_argument("--block", required=True)
    p_rb.add_argument("--blocks", required=True)

    args = parser.parse_args()
    handlers = {
        "whoami": cmd_whoami,
        "search": cmd_search,
        "create-db": cmd_create_db,
        "add-rows": cmd_add_rows,
        "create-page": cmd_create_page,
        "append-blocks": cmd_append_blocks,
        "get-db": cmd_get_db,
        "inspect": cmd_inspect,
        "get-page": cmd_get_page,
        "get-blocks": cmd_get_blocks,
        "query": cmd_query,
        "replace-blocks": cmd_replace_blocks,
    }

    try:
        handlers[args.command](args)
    except NotionError as e:
        sys.exit(f"\n노션 API 오류\n{e}")
    except FileNotFoundError as e:
        sys.exit(f"파일을 찾을 수 없습니다: {e.filename}")


if __name__ == "__main__":
    main()
