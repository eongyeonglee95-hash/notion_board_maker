# 다음에 할 일

작성일: 2026-08-13

## 오늘까지 된 것

- 노션 정리 스킬 + 서브에이전트 2개 + `/git:commit`, `/git:push` 커맨드 구축
- 노션 연결 완료 (통합 이름: `정리 에이전트`)
- 기존 노션 40개 오브젝트 분석 완료 (아래 결과 참고)
- **2026-08-13: `바이브코딩`을 "🚀 AI DEV LAB" 홈 대시보드로 재구성**
  - 흩어져 있던 `도구 사전` / `링크 모음` / `레퍼런스 모음`(구 드라이버 점검 DB) 3개를 **`AI Library`** 하나로 통합 (9행 마이그레이션, 원본은 휴지통에 30일 보관)
  - `학습 진행`(지금 공부 중), `Inbox`(일단 저장) DB 신규 생성
  - 페이지 헤더/안내 블록 재작성. 주소는 [notion_targets.json](notion_targets.json)
  - **수동으로 남은 것**: View 탭(전체/BEST/입문/Claude/Codex/MCP)과 상단 퀵버튼(➕배운 것/🔗링크/💡아이디어)은 API로 못 만듦 — 노션에서 직접 뷰 추가 + Database Button 설정 필요

## 🔴 먼저 할 것: 노션 토큰 재발급

토큰이 채팅 기록에 노출되었습니다.

1. https://www.notion.so/profile/integrations → `정리 에이전트` → Configuration
2. Internal Integration Secret → **Rotate(재발급)**
3. 새 토큰을 `.env` 의 `NOTION_TOKEN` 에 교체

---

## 1. 빈 템플릿 행 17개 삭제 (사용자 승인 완료)

스크립트 준비됨. 삭제 전 "정말 비었는지" 자동 검증하고, 내용이 있으면 건너뜁니다.

```bash
# ID 목록을 파일로 저장한 뒤
python3 .claude/skills/notion-organizer/scripts/notion.py trash-pages \
  --ids-file 아래_ID목록.txt --dry-run     # 먼저 연습 실행
python3 ... trash-pages --ids-file 아래_ID목록.txt   # 실제 삭제
```

삭제 대상 ID (17개):
```
3b32d2f5-eb90-8092-af32-f93a3483d32e
3b32d2f5-eb90-8037-ae9b-d7da0c5edb1b
2ab2d2f5-eb90-8057-9d05-c26a204751ad
2ab2d2f5-eb90-8041-9d01-cbc580eeaba5
2ab2d2f5-eb90-8140-8d2d-fa8a5020ec28
2ab2d2f5-eb90-8058-b9c3-e79d3ac72099
2ab2d2f5-eb90-8139-b78b-ce9aff340f09
2ab2d2f5-eb90-813d-acef-e378397f9158
2ab2d2f5-eb90-81dd-b648-c9e322d05f2d
2ab2d2f5-eb90-8124-be40-e3a957ee147c
2ab2d2f5-eb90-8142-8c0c-c035da44337d
2ab2d2f5-eb90-81b4-90bd-fa1ce68cfa2b
2ab2d2f5-eb90-81bc-8e30-e1fa23d489da
2ab2d2f5-eb90-8132-80a5-eab45b8c11f6
2ab2d2f5-eb90-8163-90bb-e30917b3d9e1
2ab2d2f5-eb90-81a6-a0fe-fc54da382a9f
2ab2d2f5-eb90-8103-94d5-cfb03d83c59d
```

## 2. 살릴 내용 18개를 새 DB로 이관

| 새 위치 | 옮길 것 | 원본 ID |
|---|---|---|
| 📚 AI Library | Claude Code (플러그인·statusline·`shift+tab`) | `3ac2d2f5-...-8031`, `3ac2d2f5-...-8099`, `3ac2d2f5-...-804e` |
| 📚 AI Library | GitHub (명령어 표까지 정리됨, 가장 완성도 높음) | `2ab2d2f5-...-8160` |
| 📚 AI Library | context7 MCP (`npx ctx7 setup`) | `2ab2d2f5-...-815f` |
| 📚 AI Library | Render / aiven / neon / GCP | `2ab2d2f5-...-81ae`, `2ab2d2f5-...-81b7` |
| 📚 AI Library | Codex + Firebase | `a76c5965-...` |
| 📖 강의 노트 | 카카오맵 API 키 발급 절차 | `3ac2d2f5-...-806f` |
| 📖 강의 노트 | Render 배포 2단계 (제목 없음) | `2ab2d2f5-...-81b7` |
| 📚 AI Library | 짐코딩 노션 3개, dribbble, 배포서비스 4개, 공공API 5개 | 여러 곳 |

> 2026-08-13: 목적지가 `도구 사전`/`링크 모음`에서 통합 DB **`AI Library`** 로 바뀌었습니다 (위 표는 원래 계획 그대로 두고 목적지만 갱신).

**주의**: `배포`(`...81ae`)와 제목없는 `Render 2단계`(`...81b7`)는 같은 주제 → 하나로 병합할 것.

## 3. 외부 자료 긁어오기 (사용자 요청)

AI 동호회에서 공유받은 자료가 **외부 노션(짐코딩)** 에 있어서 남편분이나 다른 사람은 못 볼 수 있음.
→ 내용을 긁어와 우리 워크스페이스에 같은 구조로 복제하고 싶다는 요청.

대상 링크 (전부 `gymcoding.notion.site`, 워크스페이스 밖이라 API 접근 불가 → WebFetch 로 시도):
- `https://gymcoding.notion.site/Claude-Code-with-AI-24c6a10d310b8077b064eca98557a416`
- `https://gymcoding.notion.site/2626a10d310b80f3a882c431c4f0ce96` (개발 기술 스택)
- `https://gymcoding.notion.site/2a46a10d310b802da28aebfdf49c6cbc` (소스코드)

> ⚠️ 저작권 확인 필요: 동호회 공유 자료를 통째로 복제해도 되는지 확인할 것.
> 개인 학습용 보관은 대개 괜찮지만, 공유 범위를 넓히는 건 별개 문제.

## 4. AI Library 채우기 — 찾아둔 사이트 (구 "링크 모음 채우기")

**Matt Pocock (`pea coak` = Matt Pocock 으로 확인)**
- `https://github.com/mattpocock/skills` — Skills for Real Engineers
- `https://claude.com/plugins/mattpocock-skills` — 플러그인 페이지
- `https://www.aihero.dev/posts` — AI 엔지니어링 글 모음
- `grill-me`: 코드 쓰기 전에 에이전트가 질문을 퍼붓게 만드는 스킬

**MCP 디렉토리**
- `https://github.com/modelcontextprotocol/servers` — 공식 레퍼런스
- `https://glama.ai/mcp/servers` — 최대 규모 마켓플레이스
- `https://top-mcps.com/` — 실사용 기준 랭킹
- `https://www.developersdigest.tech/blog/mcp-servers-directory-2026` — 카테고리별 정리

## 5. 미해결 / 확인 필요

- ~~DB 제목 관련 질문~~ → **2026-08-13 해결**. "드라이버 점검 DB"(`976b5519-...`, 스터디 바로 아래,
  실제 내용은 코딩 도구 2건)가 그 대상이었음. 이후 같은 날 `AI Library` 통합에 포함되어 소멸(휴지통에서 복구 가능).
- `AI Library` DB에 9개 행 채움 (구 도구사전 3 + 링크모음 5 + 레퍼런스모음 1, 완전중복 1건 제외).
  4번 항목의 "찾아둔 사이트"(Matt Pocock 레포·플러그인, MCP 디렉토리 4곳)는 아직 안 넣음.
- View 탭 / 상단 퀵버튼은 API로 못 만들어서 수동 설정 필요 (위 "오늘까지 된 것" 참고).
- 기존 `바이브코딩` DB (`3ac2d2f5-...-8022`) 는 아직 통합 미연결 → 내용 확인 불가
- 깨진 강의자료 링크 2개 (`35db6a86-...`) → 사용자가 "나중에 확인" 선택
- 이미지/파일만 있는 행 1개 (`2ab2d2f5-...-81dd-873a`) → 내용인지 확인 필요
- TypeScript/JavaScript/React 기초 노트 → "일단 두기" 선택함

## 6. 보안 확인 필요

`AI스터디` 페이지 (`a76c5965-...`) 에 Firebase 설정값이 평문으로 있고,
본문에 **보안 규칙이 "테스트용 전체 허용"** 이라고 적혀 있음.
client key 노출 자체는 정상이지만, 규칙이 전체 허용이면 누구나 DB를 읽고 쓸 수 있음.
실제 서비스 전에 인증 규칙 적용 필요.
