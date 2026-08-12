#!/usr/bin/env python3
"""
notion_board_maker 구동 드라이버

이 프로젝트에서 실제로 돌아가는 것은 `notion.py` CLI 하나뿐이다.
그런데 쓰기 명령(create-db / add-rows / create-page / append-blocks)은
실행하는 순간 사용자의 진짜 노션 워크스페이스에 내용을 만들어버린다.
그래서 이 드라이버는 로컬에 가짜 노션 API 서버를 띄우고 notion.py 를
그쪽으로 붙여서, 11개 명령 전부를 토큰·네트워크 없이 검증한다.

모드:
  mock        가짜 서버로 11개 명령 전부 검증 (기본값, 토큰·네트워크 불필요)
  live        진짜 노션에 읽기 전용 호출만 (whoami / search / inspect)
  live-write  진짜 노션에 점검용 DB 를 실제로 만든다 (지우려면 직접 삭제)
  fixtures    spec.json / rows.json 예시 파일만 뽑아낸다

사용법:
  python3 .claude/skills/run-notion-board-maker/driver.py mock
  python3 .claude/skills/run-notion-board-maker/driver.py live
  python3 .claude/skills/run-notion-board-maker/driver.py live --inspect <URL|ID>
  python3 .claude/skills/run-notion-board-maker/driver.py live-write --parent-page <PAGE_ID>
  python3 .claude/skills/run-notion-board-maker/driver.py fixtures --out /tmp/fx
"""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NOTION_PY = os.path.join(
    REPO, ".claude", "skills", "notion-organizer", "scripts", "notion.py"
)

RECORDED = []   # 가짜 서버가 받은 요청 전부
INJECT = []     # (status, code, message) 를 넣어두면 다음 요청 한 번만 그 에러로 응답

MOCK_DB_ID = "11111111222233334444555555555555"
MOCK_DS_ID = "aaaaaaaabbbbccccddddeeeeeeeeeeee"
MOCK_PAGE_ID = "99999999888877776666555544443333"


# ------------------------------------------------------------------ 가짜 노션 API


class MockNotion(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # 검증 출력이 요청 로그에 묻히지 않도록 죽인다

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw.decode("utf-8")) if raw else None

    def _send(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        body = self._read_body()
        RECORDED.append({
            "method": method,
            "path": self.path,
            "body": body,
            "notion_version": self.headers.get("Notion-Version"),
            "authorization": self.headers.get("Authorization"),
        })

        if INJECT:
            status, code, message = INJECT.pop(0)
            self._send(status, {"object": "error", "status": status,
                                "code": code, "message": message})
            return

        path, _, query = self.path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)

        if method == "GET" and path == "/v1/users/me":
            self._send(200, {
                "object": "user", "id": "bot-0000", "name": "가짜 통합",
                "type": "bot", "bot": {"owner": {"type": "workspace"}},
            })

        elif method == "POST" and path == "/v1/search":
            self._send(200, {"object": "list", "results": _search_results(body)})

        elif method == "POST" and path == "/v1/databases":
            self._send(200, _db_object(body.get("title", [])))

        elif method == "GET" and re.match(r"^/v1/databases/[^/]+$", path):
            self._send(200, _db_object([{"plain_text": "가짜 DB"}]))

        elif method == "GET" and re.match(r"^/v1/data_sources/[^/]+$", path):
            self._send(200, {
                "object": "data_source", "id": MOCK_DS_ID,
                "title": [{"plain_text": "기본"}],
                "properties": {
                    "도구명": {"type": "title", "title": {}},
                    "카테고리": {"type": "select", "select": {"options": [
                        {"name": "코딩", "color": "blue"},
                        {"name": "문서", "color": "green"}]}},
                },
            })

        elif method == "POST" and re.match(r"^/v1/data_sources/[^/]+/query$", path):
            self._send(200, _query_page(body))

        elif method == "POST" and path == "/v1/pages":
            page_id = uuid.uuid4().hex
            self._send(200, {"object": "page", "id": page_id,
                             "url": "https://notion.so/" + page_id})

        elif method == "GET" and re.match(r"^/v1/pages/[^/]+$", path):
            self._send(200, {
                "object": "page", "id": MOCK_PAGE_ID,
                "parent": {"type": "page_id", "page_id": "parent-0001"},
                "properties": {"이름": {"type": "title",
                                        "title": [{"plain_text": "가짜 페이지"}]}},
                "url": "https://notion.so/" + MOCK_PAGE_ID,
            })

        elif method == "GET" and re.match(r"^/v1/blocks/[^/]+/children$", path):
            block_id = path.split("/")[3]
            self._send(200, _blocks_page(block_id, params.get("start_cursor")))

        elif method == "PATCH" and re.match(r"^/v1/blocks/[^/]+/children$", path):
            self._send(200, {"object": "list", "results": []})

        else:
            self._send(404, {"object": "error", "status": 404,
                             "code": "object_not_found",
                             "message": f"가짜 서버에 없는 경로: {method} {path}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")


def _db_object(title):
    return {
        "object": "database", "id": MOCK_DB_ID, "title": title,
        "parent": {"type": "page_id", "page_id": "parent-0001"},
        "data_sources": [{"id": MOCK_DS_ID, "name": "기본"}],
        "url": "https://notion.so/" + MOCK_DB_ID,
    }


def _search_results(body):
    kind = (body or {}).get("filter", {}).get("value")
    page = {"object": "page", "id": MOCK_PAGE_ID,
            "properties": {"이름": {"type": "title",
                                    "title": [{"plain_text": "스터디"}]}}}
    ds = {"object": "data_source", "id": MOCK_DS_ID,
          "title": [{"plain_text": "강의노트DB"}]}
    if kind == "page":
        return [page]
    if kind == "data_source":
        return [ds]
    return [page, ds]


def _row(name, category, tags, when):
    return {
        "object": "page", "id": uuid.uuid4().hex,
        "properties": {
            "도구명": {"type": "title", "title": [{"plain_text": name}]},
            "카테고리": {"type": "select", "select": {"name": category}},
            "태그": {"type": "multi_select",
                     "multi_select": [{"name": t} for t in tags]},
            "날짜": {"type": "date", "date": {"start": when}},
            "메모": {"type": "rich_text", "rich_text": []},
        },
    }


def _query_page(body):
    """query 는 페이지네이션을 돈다. 커서 없으면 1페이지, 있으면 2페이지."""
    if not (body or {}).get("start_cursor"):
        return {"object": "list",
                "results": [_row("Claude Code", "코딩", ["CLI", "무료"], "2026-08-01"),
                            _row("Cursor", "코딩", ["IDE"], "2026-08-02")],
                "has_more": True, "next_cursor": "cursor-q2"}
    return {"object": "list",
            "results": [_row("Notion API", "문서", [], "2026-08-03")],
            "has_more": False, "next_cursor": None}


def _blocks_page(block_id, cursor):
    """get-blocks 의 페이지네이션 + 중첩 탐색을 둘 다 시험할 수 있는 응답."""
    if block_id == "nested-block-0001":
        return {"object": "list", "has_more": False, "results": [
            _blk("paragraph", "안쪽 문단")]}
    if not cursor:
        toggle = _blk("toggle", "접기")
        toggle["id"] = "nested-block-0001"
        toggle["has_children"] = True
        return {"object": "list", "has_more": True, "next_cursor": "cursor-b2",
                "results": [_blk("heading_2", "점검 결과"), toggle]}
    todo = _blk("to_do", "할 일")
    todo["to_do"]["checked"] = False
    return {"object": "list", "has_more": False, "results": [
        todo,
        {"object": "block", "id": uuid.uuid4().hex, "type": "code",
         "has_children": False,
         "code": {"language": "python",
                  "rich_text": [{"plain_text": "print('hi')"}]}},
        {"object": "block", "id": uuid.uuid4().hex, "type": "divider",
         "has_children": False, "divider": {}},
    ]}


def _blk(btype, text):
    return {"object": "block", "id": uuid.uuid4().hex, "type": btype,
            "has_children": False,
            btype: {"rich_text": [{"plain_text": text}]}}


def start_mock():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockNotion)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# ------------------------------------------------------------------ notion.py 로딩


def load_notion(api_base=None, no_sleep=False):
    """notion.py 를 모듈로 불러온다. api_base 를 주면 요청이 그쪽으로 간다."""
    if not os.path.exists(NOTION_PY):
        sys.exit(f"notion.py 를 찾을 수 없습니다: {NOTION_PY}")
    spec = importlib.util.spec_from_file_location("notion_client", NOTION_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if api_base:
        mod.API_BASE = api_base
    if no_sleep:
        mod.REQUEST_INTERVAL = 0  # 초당 3회 제한은 가짜 서버에 없다
    return mod


def run_cli(mod, argv):
    """notion.py 를 CLI 로 부른 것처럼 돌리고 (표준출력, 종료값) 을 돌려준다."""
    buf = io.StringIO()
    saved = sys.argv
    sys.argv = ["notion.py"] + argv
    exit_code = None
    try:
        with contextlib.redirect_stdout(buf):
            mod.main()
    except SystemExit as e:
        exit_code = e.code
    finally:
        sys.argv = saved
    return buf.getvalue(), exit_code


# ------------------------------------------------------------------ 검증 도구


PASSED, FAILED, NOTES = [], [], []


def check(label, ok, detail=""):
    if ok:
        PASSED.append(label)
        print(f"  ✅ {label}")
    else:
        FAILED.append(label)
        print(f"  ❌ {label}")
        if detail:
            print(f"     {detail}")
    return bool(ok)


def note(label, detail=""):
    """고쳐야 할 것으로 확인됐지만 통과/실패로 세지 않는 항목."""
    NOTES.append(label)
    print(f"  ⚠️  {label}")
    if detail:
        print(f"     {detail}")


def last(method, path_prefix):
    for item in reversed(RECORDED):
        if item["method"] == method and item["path"].startswith(path_prefix):
            return item
    return None


def all_of(method, pattern):
    return [i for i in RECORDED
            if i["method"] == method and re.match(pattern, i["path"])]


def first_json(text):
    """출력 중간에 진행 로그가 섞여 있어도 마지막 JSON 덩어리를 꺼낸다."""
    start = text.index("{")
    return json.loads(text[start:])


# ------------------------------------------------------------------ 픽스처


def write_fixtures(out_dir):
    os.makedirs(out_dir, exist_ok=True)

    spec = {
        "title": "드라이버 점검 DB",
        "icon": "🧪",
        "description": "run-notion-board-maker 드라이버가 만든 점검용 DB",
        "properties": {
            "도구명": {"title": {}},
            "카테고리": {"select": {"options": [
                {"name": "코딩", "color": "blue"},
                {"name": "문서", "color": "green"}]}},
            "태그": {"multi_select": {"options": [
                {"name": "CLI", "color": "purple"},
                {"name": "무료", "color": "yellow"}]}},
            "숙련도": {"select": {"options": [
                {"name": "익힘", "color": "green"},
                {"name": "써봄", "color": "yellow"}]}},
            "링크": {"url": {}},
        },
    }

    def row(name, category, tags, level, url, icon, body):
        return {
            "icon": icon,
            "properties": {
                "도구명": {"title": [{"text": {"content": name}}]},
                "카테고리": {"select": {"name": category}},
                "태그": {"multi_select": [{"name": t} for t in tags]},
                "숙련도": {"select": {"name": level}},
                "링크": {"url": url},
            },
            "children": [{
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [
                    {"type": "text", "text": {"content": body}}]}}],
        }

    rows = [
        row("Claude Code", "코딩", ["CLI"], "익힘",
            "https://claude.com/claude-code", "🤖", "터미널에서 쓰는 코딩 에이전트."),
        row("Notion API", "문서", ["무료"], "써봄",
            "https://developers.notion.com", "📓",
            "2025-09-03 버전부터 구조가 바뀌었다."),
    ]

    page = {
        "title": "드라이버 점검 페이지",
        "icon": "📄",
        "children": [
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": [
                 {"type": "text", "text": {"content": "점검 결과"}}]}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": [
                 {"type": "text", "text": {"content": "드라이버가 만든 페이지입니다."}}]}},
        ],
    }

    # 100개 분할을 시험하려면 블록이 100개를 넘어야 한다
    big = {"children": [
        {"object": "block", "type": "bulleted_list_item",
         "bulleted_list_item": {"rich_text": [
             {"type": "text", "text": {"content": f"항목 {i}"}}]}}
        for i in range(1, 251)]}

    paths = {}
    for name, data in (("spec.json", spec), ("rows.json", rows),
                       ("page.json", page), ("blocks-250.json", big)):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        paths[name] = p
    return paths


# ------------------------------------------------------------------ mock 모드


def mode_mock(args):
    # 진짜 .env 토큰을 절대 읽지 않도록 가짜 토큰을 박아둔다 (ntn_ 검사를 통과해야 함)
    os.environ["NOTION_TOKEN"] = "ntn_fake_token_for_driver"

    server, port = start_mock()
    base = f"http://127.0.0.1:{port}/v1"
    print(f"가짜 노션 API: {base}")

    mod = load_notion(api_base=base, no_sleep=True)
    fx_dir = getattr(args, "fixtures", None) or tempfile.mkdtemp(prefix="nbm-driver-")
    fx = write_fixtures(fx_dir)
    print(f"픽스처: {fx_dir}\n")

    try:
        print("[1] whoami")
        out, code = run_cli(mod, ["whoami"])
        check("연결 성공을 출력한다", "연결 성공" in out, out.strip() or str(code))
        check("API 버전 2025-09-03 을 찍는다", "2025-09-03" in out)
        req = last("GET", "/v1/users/me")
        check("Notion-Version 헤더가 2025-09-03", req["notion_version"] == "2025-09-03",
              req["notion_version"])
        check("Authorization 이 Bearer 로 붙는다",
              req["authorization"].startswith("Bearer ntn_"))

        print("\n[2] search")
        out, _ = run_cli(mod, ["search", "--type", "page"])
        check("페이지 검색에 제목이 나온다", "스터디" in out, out.strip())
        check("search 필터가 object=page 로 간다",
              last("POST", "/v1/search")["body"].get("filter")
              == {"property": "object", "value": "page"})
        out, _ = run_cli(mod, ["search", "--type", "data_source"])
        check("데이터소스 검색에 제목이 나온다", "강의노트DB" in out, out.strip())

        print("\n[3] create-db")
        out, code = run_cli(mod, ["create-db", "--parent-page", MOCK_PAGE_ID,
                                  "--spec", fx["spec.json"]])
        body = last("POST", "/v1/databases")["body"]
        check("parent 가 page_id 다", body["parent"]["type"] == "page_id")
        check("속성이 initial_data_source.properties 아래로 간다 (2025-09-03)",
              "properties" in body.get("initial_data_source", {}),
              json.dumps(list(body.keys()), ensure_ascii=False))
        check("최상위 properties 를 보내지 않는다 (구버전 형식 아님)",
              "properties" not in body, json.dumps(list(body.keys())))
        check("title 이 리치텍스트 배열이다",
              body["title"][0]["text"]["content"] == "드라이버 점검 DB")
        check("icon 이 emoji 로 붙는다",
              body.get("icon") == {"type": "emoji", "emoji": "🧪"})
        check("data_source_id 를 출력한다",
              first_json(out).get("data_source_id") == MOCK_DS_ID,
              out.strip() or str(code))

        print("\n[4] add-rows")
        before = len(all_of("POST", r"^/v1/pages$"))
        out, code = run_cli(mod, ["add-rows", "--data-source", MOCK_DS_ID,
                                  "--rows", fx["rows.json"]])
        pages = all_of("POST", r"^/v1/pages$")
        check("행 2개가 만들어졌다", len(pages) - before == 2,
              f"{len(pages) - before}개 / {code}")
        parent = pages[-1]["body"]["parent"]
        check("행의 parent 가 data_source_id 다 (구: database_id)",
              parent == {"type": "data_source_id", "data_source_id": MOCK_DS_ID},
              json.dumps(parent, ensure_ascii=False))
        check("결과 JSON 에 created 2 가 들어있다",
              first_json(out).get("created") == 2, out.strip())

        print("\n[5] create-page")
        out, _ = run_cli(mod, ["create-page", "--parent-page", MOCK_PAGE_ID,
                               "--spec", fx["page.json"]])
        props = all_of("POST", r"^/v1/pages$")[-1]["body"]["properties"]
        check("일반 페이지는 properties.title 을 쓴다", "title" in props,
              json.dumps(list(props.keys()), ensure_ascii=False))
        check("url 을 출력한다", "url" in first_json(out), out.strip())

        print("\n[6] append-blocks — 250개 분할")
        before = len(all_of("PATCH", r"^/v1/blocks/"))
        out, _ = run_cli(mod, ["append-blocks", "--block", MOCK_PAGE_ID,
                               "--blocks", fx["blocks-250.json"]])
        sizes = [len(p["body"]["children"])
                 for p in all_of("PATCH", r"^/v1/blocks/")[before:]]
        check("250개가 100/100/50 으로 쪼개진다", sizes == [100, 100, 50], str(sizes))
        check("개수를 보고한다", "250개" in out, out.strip())

        print("\n[7] get-db")
        out, _ = run_cli(mod, ["get-db", "--database", MOCK_DB_ID])
        check("data_sources 를 돌려준다",
              first_json(out)["data_sources"][0]["id"] == MOCK_DS_ID, out.strip())

        print("\n[8] get-page")
        out, _ = run_cli(mod, ["get-page", "--page", MOCK_PAGE_ID])
        parsed = first_json(out)
        check("제목을 뽑아낸다", parsed["title"] == "가짜 페이지", out.strip())
        check("parent 를 같이 준다", parsed["parent"]["type"] == "page_id")

        print("\n[9] get-blocks — 페이지네이션 + 중첩")
        out, _ = run_cli(mod, ["get-blocks", "--block", MOCK_PAGE_ID])
        lines = out.splitlines()
        check("heading_2 가 ## 로 나온다", "## 점검 결과" in lines, out)
        check("toggle 이 ▸ 로 나온다", "▸ 접기" in lines, out)
        check("중첩 블록이 들여쓰기된다", "  안쪽 문단" in lines, out)
        check("2페이지째도 이어서 읽는다", "- [ ] 할 일" in lines, out)
        check("코드 블록이 ``` 로 감싼다", "```python" in out and "print('hi')" in out)
        check("divider 가 --- 로 나온다", "---" in lines, out)

        print("\n[10] query — 페이지네이션 + 값 단순화")
        out, _ = run_cli(mod, ["query", "--data-source", MOCK_DS_ID])
        parsed = first_json(out)
        check("2페이지를 합쳐 3행을 준다", parsed["count"] == 3, out.strip())
        row0 = parsed["rows"][0]["properties"]
        check("title 이 문자열로 펴진다", row0["도구명"] == "Claude Code", str(row0))
        check("select 가 이름만 남는다", row0["카테고리"] == "코딩", str(row0))
        check("multi_select 가 이름 배열이 된다", row0["태그"] == ["CLI", "무료"], str(row0))
        check("date 가 start 만 남는다", row0["날짜"] == "2026-08-01", str(row0))
        check("빈 rich_text 는 빈 문자열", row0["메모"] == "", repr(row0["메모"]))

        print("\n[11] inspect — DB 로 판별")
        out, _ = run_cli(mod, ["inspect", MOCK_DB_ID])
        check("종류를 데이터베이스로 찍는다", "종류: 데이터베이스" in out, out.strip())
        check("데이터소스 ID 를 보여준다", MOCK_DS_ID in out)
        check("select 옵션과 색을 펼쳐준다", "코딩(blue)" in out, out.strip())

        print("\n[12] inspect — DB 조회가 실패하면 페이지로 넘어간다")
        INJECT.append((404, "object_not_found", "Not a database"))
        out, _ = run_cli(mod, ["inspect", MOCK_PAGE_ID])
        check("페이지로 판별한다", "종류: 페이지" in out, out.strip())

        print("\n[13] inspect — URL 에서 ID 뽑기")
        dashed = "11111111-2222-3333-4444-555555555555"
        cases = [
            (MOCK_DB_ID, "맨 ID"),
            (dashed, "하이픈 UUID"),
            ("  " + MOCK_DB_ID + "  ", "앞뒤 공백"),
            ("https://www.notion.so/" + MOCK_DB_ID, "제목 없는 URL"),
            ("https://www.notion.so/" + dashed, "URL 안의 하이픈 UUID"),
            ("https://www.notion.so/스터디-" + MOCK_DB_ID, "한글 제목 (그대로)"),
            ("https://www.notion.so/%EC%8A%A4%ED%84%B0%EB%94%94-" + MOCK_DB_ID,
             "퍼센트 인코딩된 한글 제목 (브라우저에서 복사한 형태)"),
            ("https://www.notion.so/Cafe-" + MOCK_DB_ID,
             "제목 끝이 16진수 (Cafe, Dec, 2024 …)"),
            ("https://www.notion.so/2024-" + MOCK_DB_ID, "제목이 숫자로 끝남"),
            ("https://www.notion.so/팀/AI-도구-" + MOCK_DB_ID, "경로가 여러 단계"),
            ("https://www.notion.so/My-Notes-" + MOCK_DB_ID + "?v=" + "a" * 32,
             "?v= 뷰 ID 무시"),
            ("https://www.notion.so/Notes-" + MOCK_DB_ID + "?pvs=4", "?pvs= 무시"),
            ("https://www.notion.so/Notes-" + MOCK_DB_ID + "#block", "# 조각 무시"),
        ]
        for raw, label in cases:
            got = mod._extract_id(raw)
            check(f"ID 추출: {label}", got == MOCK_DB_ID, f"→ {got}")

        print("\n[14] 리치텍스트 2000자 제한")
        piece = mod.rich_text("가" * 5000)
        check("2000자에서 잘리고 … 가 붙는다",
              len(piece["text"]["content"]) == 2000
              and piece["text"]["content"].endswith("…"),
              str(len(piece["text"]["content"])))

        print("\n[15] 에러가 한국어 안내로 바뀐다")
        INJECT.append((404, "object_not_found", "Could not find database"))
        _, code = run_cli(mod, ["get-db", "--database", MOCK_DB_ID])
        check("object_not_found 에 통합 연결 안내가 붙는다",
              "연결" in str(code) and "노션 API 오류" in str(code), str(code))
        INJECT.append((401, "unauthorized", "API token is invalid"))
        _, code = run_cli(mod, ["whoami"])
        check("unauthorized 에 토큰 확인 안내가 붙는다", "NOTION_TOKEN" in str(code),
              str(code))
        INJECT.append((429, "rate_limited", "Too many requests"))
        _, code = run_cli(mod, ["whoami"])
        check("rate_limited 에 재시도 안내가 붙는다", "잠시 후" in str(code), str(code))

        # 토큰 검사는 _validate_token 을 직접 부른다.
        # CLI 로 돌리면 빈 값일 때 진짜 .env 를 읽어버려서, 실제 토큰이
        # 가짜 서버로 흘러간다.
        print("\n[16] 토큰 검사")
        check("빈 토큰이면 발급 안내로 끝난다",
              "비어 있습니다" in _token_error(mod, ""), _token_error(mod, ""))
        check("안내 문구가 그대로면 잡아낸다",
              "실제 토큰이 들어가지 않았습니다" in _token_error(mod, "여기에_토큰_붙여넣기"))
        check("ntn_ 로 시작하지 않으면 막는다",
              "형식이 올바르지 않습니다" in _token_error(mod, "sk-1234567890"))
        check("한글이 섞인 토큰을 막는다",
              "ASCII 가 아닌" in _token_error(mod, "ntn_토큰"),
              _token_error(mod, "ntn_토큰"))
        check("따옴표로 감싼 토큰은 벗겨서 받아준다",
              mod._validate_token('"ntn_abc123"') == "ntn_abc123")
        check("정상 토큰은 통과시킨다", mod._validate_token("ntn_abc123") == "ntn_abc123")

        print("\n[17] 없는 파일 처리")
        _, code = run_cli(mod, ["create-db", "--parent-page", MOCK_PAGE_ID,
                                "--spec", "/nope/none.json"])
        check("없는 spec 이면 친절한 메시지로 끝난다", "찾을 수 없습니다" in str(code),
              str(code))

        print("\n[18] 알려진 문제 — ASCII 가 아닌 ID")
        crashed = False
        try:
            run_cli(mod, ["get-page", "--page", "한글아이디"])
        except UnicodeEncodeError:
            crashed = True
        if crashed:
            note("한글이 섞인 ID/URL 을 주면 UnicodeEncodeError 로 죽는다",
                 "notion.py 의 request() 가 URL 을 그대로 http.client 에 넘긴다. "
                 "ID 는 항상 32자리 16진수여야 한다.")
        else:
            check("한글 ID 가 친절한 메시지로 처리된다", True)

    finally:
        server.shutdown()
        server.server_close()

    print(f"\n요청 {len(RECORDED)}건 · 통과 {len(PASSED)} · 실패 {len(FAILED)}"
          f" · 알려진 문제 {len(NOTES)}")
    if FAILED:
        print("실패: " + ", ".join(FAILED))
        return 1
    print("전체 통과")
    return 0


def _token_error(mod, token):
    """_validate_token 이 뱉는 종료 메시지. 통과하면 빈 문자열."""
    try:
        mod._validate_token(token)
    except SystemExit as e:
        return str(e.code)
    return ""


# ------------------------------------------------------------------ live 모드


def mode_live(args):
    mod = load_notion()

    print("[1] whoami — 진짜 노션")
    out, code = run_cli(mod, ["whoami"])
    print(out.rstrip() or str(code))
    if not check("토큰이 살아있다", "연결 성공" in out, str(code)):
        return 1

    print("\n[2] search --type page")
    out, _ = run_cli(mod, ["search", "--type", "page"])
    lines = [l for l in out.splitlines() if l.strip()]
    print("\n".join(lines[:5]))
    if len(lines) > 5:
        print(f"  … 총 {len(lines)}건")
    check("통합에 연결된 페이지가 있다", len(lines) > 0,
          "노션에서 페이지 ··· > 연결 로 통합을 붙여주세요")

    print("\n[3] search --type data_source")
    out, _ = run_cli(mod, ["search", "--type", "data_source"])
    lines = [l for l in out.splitlines() if l.strip()]
    print("\n".join(lines[:5]))
    found = re.findall(r"^data_source\s+(\S+)\s+(.*)$", out, re.M)

    # 찾은 데이터소스를 하나씩 읽어본다. 행이 있는 것을 만나면 거기서 멈춘다.
    if found:
        print("\n[4] query — 찾은 데이터소스를 읽기 전용으로 조회")
        for ds_id, title in found[:5]:
            out, code = run_cli(mod, ["query", "--data-source", ds_id])
            if "{" not in out:
                check(f"query 실패: {title}", False, str(code))
                break
            count = first_json(out).get("count", 0)
            print(f"  {title}: {count}행")
            if count:
                sample = first_json(out)["rows"][0]["properties"]
                print("  첫 행: " + json.dumps(sample, ensure_ascii=False)[:160])
                check("데이터소스에서 행을 읽어 값을 펴낸다", True)
                break
        else:
            check("데이터소스 조회는 되지만 행이 있는 DB 를 못 찾았다", True)

    target = getattr(args, "inspect", None)
    if target:
        print(f"\n[5] inspect {target}")
        out, code = run_cli(mod, ["inspect", target])
        print(out.rstrip() or str(code))
        check("대상 구조를 읽어온다", "종류:" in out, str(code))

    print(f"\n통과 {len(PASSED)} · 실패 {len(FAILED)}")
    return 1 if FAILED else 0


# ------------------------------------------------------------------ live-write 모드


def mode_live_write(args):
    parent = args.parent_page or os.environ.get("NOTION_PARENT_PAGE_ID")
    if not parent:
        sys.exit("--parent-page <PAGE_ID> 가 필요합니다.\n"
                 "  `driver.py live` 로 페이지 ID 를 먼저 확인하세요.")

    print("⚠️  진짜 노션 워크스페이스에 DB 를 만듭니다. 지우려면 노션에서 직접 삭제하세요.\n")
    fx_dir = getattr(args, "fixtures", None) or tempfile.mkdtemp(prefix="nbm-driver-")
    fx = write_fixtures(fx_dir)
    mod = load_notion()

    print("[1] create-db")
    out, code = run_cli(mod, ["create-db", "--parent-page", parent,
                              "--spec", fx["spec.json"]])
    print(out.rstrip() or str(code))
    if not check("DB 가 만들어졌다", "{" in out, str(code)):
        return 1
    created = first_json(out)

    print("\n[2] add-rows")
    out, code = run_cli(mod, ["add-rows", "--data-source", created["data_source_id"],
                              "--rows", fx["rows.json"]])
    print(out.rstrip() or str(code))
    check("행 2개가 들어갔다", "{" in out and first_json(out).get("created") == 2,
          str(code))

    print("\n[3] query — 방금 넣은 행 되읽기")
    out, code = run_cli(mod, ["query", "--data-source", created["data_source_id"]])
    ok = "{" in out and first_json(out).get("count") == 2
    check("넣은 행이 그대로 읽힌다", ok, out.rstrip() or str(code))
    if ok:
        for row in first_json(out)["rows"]:
            print("   ", json.dumps(row["properties"], ensure_ascii=False))

    print(f"\n만들어진 DB: {created.get('url', '')}")
    print(f"통과 {len(PASSED)} · 실패 {len(FAILED)}")
    return 1 if FAILED else 0


# ------------------------------------------------------------------ fixtures 모드


def mode_fixtures(args):
    out_dir = args.out or tempfile.mkdtemp(prefix="nbm-fixtures-")
    for name, path in write_fixtures(out_dir).items():
        print(f"{name:16} {path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="notion_board_maker 구동 드라이버")
    sub = parser.add_subparsers(dest="mode")

    p_mock = sub.add_parser("mock", help="가짜 서버로 전체 검증 (기본값)")
    p_mock.add_argument("--fixtures", help="픽스처를 쓸 디렉토리")

    p_live = sub.add_parser("live", help="진짜 노션에 읽기 전용 호출")
    p_live.add_argument("--inspect", help="구조를 확인할 노션 URL 또는 ID")

    p_w = sub.add_parser("live-write", help="진짜 노션에 점검용 DB 를 만든다")
    p_w.add_argument("--parent-page")
    p_w.add_argument("--fixtures")

    p_f = sub.add_parser("fixtures", help="spec/rows 예시 JSON 뽑기")
    p_f.add_argument("--out")

    args = parser.parse_args()
    handlers = {"mock": mode_mock, "live": mode_live,
                "live-write": mode_live_write, "fixtures": mode_fixtures}
    sys.exit(handlers[args.mode or "mock"](args))


if __name__ == "__main__":
    main()
