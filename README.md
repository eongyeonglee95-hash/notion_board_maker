# 노션 정리 에이전트

엉망으로 흩어진 메모·자료·리스트를 노션의 잘 정리된 데이터베이스로 만들어주는 Claude Code 에이전트입니다.

정리 방법을 고민할 필요가 없습니다. 내용을 던지면 구조를 제안하고, 확인만 하면 노션에 만들어집니다.

## 무엇이 다른가

기존 방식은 이렇습니다.

```
어디에 넣지? → 페이지 만들고 → 그 안에 또 페이지 → 나중에 못 찾음
```

이 에이전트는 이렇게 합니다.

```
내용 분석 → 반복되는 성질을 속성으로 추출 → DB 1개 + 필터 가능한 속성
```

폴더를 파는 대신 속성을 붙입니다. 나중에 필터와 정렬로 원하는 것만 볼 수 있습니다.

## 준비 (처음 한 번, 5분)

### 1. 노션 토큰 발급

1. https://www.notion.so/profile/integrations → **New integration**
2. 이름 입력 후 저장, **Internal Integration Secret** 복사 (`ntn_` 으로 시작)
3. **Capabilities** 에서 `Insert content` 가 켜져 있는지 확인

### 2. 토큰 저장

```bash
cp .env.example .env
```

`.env` 파일을 열어 토큰을 붙여넣습니다.

> `.env` 는 `.gitignore` 로 차단되어 깃허브에 올라가지 않습니다.

### 3. 노션 페이지에 통합 연결 (제일 많이 빠뜨림)

노션에서 정리 내용을 담을 페이지를 열고 → 우측 상단 **···** → **연결** → 만든 통합 선택

부모 페이지에 연결하면 하위 페이지는 자동 상속됩니다.

### 4. 확인

```bash
python3 .claude/skills/notion-organizer/scripts/notion.py whoami
python3 .claude/skills/notion-organizer/scripts/notion.py search --type page
```

자세한 안내: [setup.md](.claude/skills/notion-organizer/references/setup.md)

## 사용법

Claude Code 를 열고 그냥 말하면 됩니다.

```
내가 정리해둔 AI 도구 리스트 노션에 정리해줘
tools.md 이거 표로 만들어서 노션에 올려줘
이 회의록들 노션 DB로 만들어줘
```

동작 순서:

1. 원본을 전부 읽습니다
2. 항목이 많으면 `content-analyzer` 서브에이전트가 분석합니다
3. `schema-designer` 가 속성 구성과 색을 설계합니다
4. **만들기 전에 표로 미리 보여줍니다** — 여기서 고칠 수 있습니다
5. 노션에 생성하고 링크를 줍니다

## 커스텀 커맨드

| 커맨드 | 하는 일 |
|--------|---------|
| `/git:commit` | 변경사항을 한국어 메시지로 커밋 (토큰 유출 검사 포함) |
| `/git:push` | origin 에 푸시 (푸시 전 토큰 재검사) |

두 커맨드 모두 커밋 내용에 `ntn_`, `sk-`, `ghp_` 같은 토큰 패턴이 있으면 중단합니다.

## 구조

```
.claude/
├── skills/notion-organizer/
│   ├── SKILL.md              에이전트 동작 규칙과 정리 3원칙
│   ├── references/
│   │   ├── notion-api.md     API 스펙 (2025-09-03)
│   │   ├── schema-patterns.md 정리 유형별 DB 스키마 6종
│   │   ├── formatting.md     색 배정·속성 순서·표 규칙
│   │   └── setup.md          토큰 발급 안내
│   └── scripts/notion.py     노션 API 클라이언트 (의존성 없음)
├── agents/
│   ├── content-analyzer.md   원본 분석 서브에이전트
│   └── schema-designer.md    스키마 설계 서브에이전트
└── commands/git/
    ├── commit.md
    └── push.md
```

## 정리 3원칙

이 에이전트가 따르는 규칙입니다.

**1. 폴더를 파지 말고 속성을 붙인다**
페이지 안에 페이지를 만들면 어디 넣었는지 기억해야 합니다. DB 하나에 속성으로 분류하면 필터로 찾습니다.

**2. 한 항목 = 한 행**
"Claude Code 사용법"과 "Cursor 사용법"은 별개의 행입니다. 상세 내용은 각 행의 페이지 본문에 들어갑니다.

**3. 속성은 5~7개까지만**
많으면 채우다 지쳐서 안 쓰게 됩니다. 나중에 **필터하거나 정렬할 것**만 속성으로 만듭니다.

## API 버전 주의

노션 API 는 2025-09-03 버전부터 구조가 바뀌었습니다.

| 작업 | 이전 | 현재 |
|---|---|---|
| DB 생성 | `properties` | `initial_data_source.properties` |
| 행 추가 | `parent.database_id` | `parent.data_source_id` |
| 관계 속성 | `database_id` | `data_source_id` |

예전 방식으로 호출하면 전부 실패합니다. 이 프로젝트는 최신 스펙을 따릅니다.

## 직접 스크립트 쓰기

```bash
S=.claude/skills/notion-organizer/scripts/notion.py

python3 $S whoami                                       # 연결 확인
python3 $S search --type page                           # 접근 가능한 페이지
python3 $S create-db --parent-page <ID> --spec spec.json # DB 생성
python3 $S add-rows --data-source <ID> --rows rows.json  # 행 추가
python3 $S get-db --database <ID>                        # 데이터소스 ID 확인
```
