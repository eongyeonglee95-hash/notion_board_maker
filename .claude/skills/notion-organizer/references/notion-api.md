# 노션 API 참고 (Notion-Version: 2025-09-03)

## 가장 중요: 2025-09-03 에서 바뀐 것

노션은 2025-09-03 버전부터 **데이터베이스와 데이터소스를 분리**했다.
데이터베이스는 껍데기(컨테이너)이고, 실제 속성과 행은 그 안의 **데이터소스**에 들어간다.
하나의 데이터베이스가 여러 데이터소스를 가질 수 있다.

예전 코드를 그대로 쓰면 `validation_error` 가 난다.

| | 2025-09-03 이전 | **2025-09-03 이후** |
|---|---|---|
| DB 생성 시 속성 위치 | `properties` (최상위) | `initial_data_source.properties` |
| 행 추가 시 부모 | `{"database_id": "..."}` | `{"type": "data_source_id", "data_source_id": "..."}` |
| 관계(relation) 대상 | `database_id` | `data_source_id` |
| DB 조회 응답 | `properties` 포함 | `data_sources: [{id, name}]` 포함 |

**DB를 만들면 반드시 응답의 `data_sources[0].id` 를 저장해야 한다.** 이게 행을 넣을 주소다.

## 요청 공통 헤더

```
Authorization: Bearer <NOTION_TOKEN>
Notion-Version: 2025-09-03
Content-Type: application/json
```

## 데이터베이스 생성

`POST /v1/databases`

```json
{
  "parent": { "type": "page_id", "page_id": "부모_페이지_ID" },
  "title": [{ "type": "text", "text": { "content": "AI 개발도구" } }],
  "icon": { "type": "emoji", "emoji": "🛠️" },
  "initial_data_source": {
    "properties": {
      "도구명":   { "title": {} },
      "카테고리": { "select": { "options": [
                      { "name": "코딩", "color": "blue" },
                      { "name": "문서", "color": "green" }
                  ]}},
      "태그":     { "multi_select": { "options": [
                      { "name": "무료", "color": "gray" }
                  ]}},
      "숙련도":   { "select": { "options": [
                      { "name": "안써봄", "color": "gray" },
                      { "name": "써봄",   "color": "yellow" },
                      { "name": "익힘",   "color": "green" }
                  ]}},
      "링크":     { "url": {} },
      "메모":     { "rich_text": {} },
      "추가일":   { "date": {} }
    }
  }
}
```

응답:
```json
{
  "id": "데이터베이스_ID",
  "data_sources": [{ "id": "데이터소스_ID", "name": "AI 개발도구" }],
  "url": "https://www.notion.so/..."
}
```

## 행(페이지) 추가

`POST /v1/pages`

```json
{
  "parent": { "type": "data_source_id", "data_source_id": "데이터소스_ID" },
  "icon": { "type": "emoji", "emoji": "🤖" },
  "properties": {
    "도구명":   { "title": [{ "text": { "content": "Claude Code" } }] },
    "카테고리": { "select": { "name": "코딩" } },
    "태그":     { "multi_select": [{ "name": "무료" }, { "name": "CLI" }] },
    "숙련도":   { "select": { "name": "익힘" } },
    "링크":     { "url": "https://claude.com/claude-code" },
    "메모":     { "rich_text": [{ "text": { "content": "터미널에서 쓰는 코딩 에이전트" } }] },
    "추가일":   { "date": { "start": "2026-08-12" } }
  },
  "children": [ "...본문 블록..." ]
}
```

### 속성 값 형식 (자주 틀리는 부분)

| 속성 타입 | 값 형식 |
|---|---|
| `title` | `{"title": [{"text": {"content": "..."}}]}` |
| `rich_text` | `{"rich_text": [{"text": {"content": "..."}}]}` |
| `select` | `{"select": {"name": "옵션명"}}` — 객체 하나 |
| `multi_select` | `{"multi_select": [{"name": "A"}, {"name": "B"}]}` — 배열 |
| `status` | `{"status": {"name": "진행중"}}` |
| `date` | `{"date": {"start": "2026-08-12"}}` — ISO 8601 |
| `url` | `{"url": "https://..."}` — 문자열 그대로 |
| `checkbox` | `{"checkbox": true}` |
| `number` | `{"number": 42}` |
| `relation` | `{"relation": [{"id": "페이지_ID"}]}` |

select 옵션에 스키마에 없는 이름을 넣으면 자동으로 추가된다(색은 랜덤).
색을 통제하려면 스키마에 미리 정의해둔다.

## 본문 블록

`children` 배열 또는 `PATCH /v1/blocks/{id}/children`

```json
{ "object": "block", "type": "heading_2",
  "heading_2": { "rich_text": [{ "text": { "content": "설치" } }] } }

{ "object": "block", "type": "callout",
  "callout": {
    "rich_text": [{ "text": { "content": "토큰이 필요합니다" } }],
    "icon": { "type": "emoji", "emoji": "💡" },
    "color": "blue_background"
  }}

{ "object": "block", "type": "code",
  "code": {
    "rich_text": [{ "text": { "content": "npm install -g @anthropic-ai/claude-code" } }],
    "language": "bash"
  }}

{ "object": "block", "type": "bulleted_list_item",
  "bulleted_list_item": { "rich_text": [{ "text": { "content": "항목" } }] } }

{ "object": "block", "type": "toggle",
  "toggle": {
    "rich_text": [{ "text": { "content": "자세히" } }],
    "children": [ "...중첩 블록..." ]
  }}

{ "object": "block", "type": "divider", "divider": {} }
```

### 정적 표 블록

반복되는 데이터는 DB를 쓰고, 표 블록은 **문서 안의 작은 비교표**에만 쓴다.

```json
{ "object": "block", "type": "table",
  "table": {
    "table_width": 3,
    "has_column_header": true,
    "has_row_header": false,
    "children": [
      { "type": "table_row", "table_row": { "cells": [
          [{ "text": { "content": "옵션" } }],
          [{ "text": { "content": "설명" } }],
          [{ "text": { "content": "기본값" } }]
      ]}},
      { "type": "table_row", "table_row": { "cells": [
          [{ "text": { "content": "--verbose" } }],
          [{ "text": { "content": "상세 출력" } }],
          [{ "text": { "content": "false" } }]
      ]}}
    ]
  }}
```

주의:
- `table_width` 와 모든 행의 셀 개수가 **정확히 일치**해야 한다. 안 맞으면 검증 에러.
- 각 셀은 **리치 텍스트 배열의 배열**이다. 문자열을 그냥 넣으면 안 된다.
- 표를 만들 때 `children` 에 최소 1개 행이 있어야 한다.
- 셀 안에서는 줄바꿈이 어색하다. 긴 내용은 DB로.

## 제한값

| 항목 | 제한 |
|---|---|
| 요청 속도 | 평균 초당 3회 |
| 한 요청의 블록 수 | 100개 |
| 리치 텍스트 한 조각 | 2000자 |
| 배열 요소 | 100개 |
| URL | 2000자 |
| 중첩 깊이 | 2단계 (children 안의 children 까지) |

100개를 넘는 블록은 먼저 100개로 페이지를 만들고, 나머지를 `PATCH /v1/blocks/{page_id}/children` 로 이어붙인다.

## 자주 만나는 에러

| 코드 | 원인 | 해결 |
|---|---|---|
| `unauthorized` | 토큰이 틀림 | `.env` 의 NOTION_TOKEN 확인 |
| `object_not_found` | ID가 틀렸거나 통합이 연결 안 됨 | 노션 페이지 ··· > 연결 > 통합 선택 |
| `restricted_resource` | 통합에 쓰기 권한 없음 | 통합 설정에서 Insert/Update content 켜기 |
| `validation_error` | 요청 형식 오류 | 대개 select 를 배열로 넣었거나 표 셀 개수 불일치 |
| `rate_limited` | 초당 3회 초과 | 요청 사이 0.34초 대기 |

## 페이지 ID 추출

노션 URL 에서 32자리 16진수가 ID다.

```
https://www.notion.so/워크스페이스/제목-3ac2d2f5eb908022adaac7126cebe77d?v=...
                                        └─────────── 이 부분 ───────────┘
```

하이픈이 없어도 API가 받아준다. `?v=` 뒤의 값은 **뷰 ID**이며 페이지 ID가 아니다.
URL에 `?v=` 가 있으면 그 페이지는 **데이터베이스**다.

## API로 안 되는 것

아래는 사용자가 노션에서 직접 클릭해야 한다. 대신 방법을 안내한다.

- **뷰 생성/변경** (보드, 캘린더, 갤러리, 타임라인)
- **필터·정렬 저장**
- **속성 열 너비, 숨김**
- **페이지 커버 이미지 업로드** (외부 URL 지정은 가능)
