# 노션 연결 설정 (처음 한 번만)

전체 5분. 순서대로 따라오면 된다.

---

## 1단계 — 통합(Integration) 만들기

1. https://www.notion.so/profile/integrations 접속
2. **New integration** 클릭
3. 입력:
   - **Name**: `정리 에이전트` (아무 이름이나)
   - **Associated workspace**: 본인 워크스페이스 선택
   - **Type**: Internal
4. **Save** 클릭
5. 다음 화면의 **Configuration** 탭에서 **Internal Integration Secret** 의 **Show → Copy**
   - `ntn_` 으로 시작하는 긴 문자열이다.

> 이 토큰은 비밀번호와 같다. 남에게 보여주거나 깃허브에 올리면 안 된다.
> 이 프로젝트의 `.gitignore` 가 `.env` 를 막아두었지만, 다른 곳에 붙여넣지 않도록 주의한다.

---

## 2단계 — 토큰 저장

프로젝트 루트에 `.env` 파일을 만들고:

```
NOTION_TOKEN=ntn_여기에_복사한_토큰
```

`.env.example` 을 복사해서 쓰면 된다:

```bash
cp .env.example .env
```

---

## 3단계 — 권한 확인

통합 설정 화면의 **Capabilities** 에서 아래가 켜져 있어야 한다:

- [x] Read content
- [x] Update content
- [x] **Insert content**  ← 이게 꺼져 있으면 아무것도 못 만든다

---

## 4단계 — 페이지에 통합 연결 (제일 많이 빠뜨리는 단계)

**토큰만 있으면 아무것도 안 된다.** 노션에서 페이지를 명시적으로 연결해줘야 한다.

1. 노션에서 정리한 내용을 담을 **부모 페이지**를 연다 (없으면 새로 만든다)
2. 우측 상단 **···** 클릭
3. **연결** (또는 Connections) 메뉴
4. 1단계에서 만든 통합 이름 선택
5. **확인** 클릭

> 부모 페이지에 연결하면 그 **하위 페이지는 자동으로 상속**된다.
> 그래서 "정리함" 같은 페이지 하나를 만들어 거기에 연결해두면 편하다.

---

## 5단계 — 연결 테스트

```bash
python3 .claude/skills/notion-organizer/scripts/notion.py whoami
```

성공하면:
```
연결 성공: 정리 에이전트 (id: ...)
API 버전: 2025-09-03
```

이어서 접근 가능한 페이지를 확인한다:

```bash
python3 .claude/skills/notion-organizer/scripts/notion.py search --type page
```

여기 목록이 비어 있으면 4단계를 안 한 것이다.

---

## 부모 페이지 ID 찾기

노션 페이지 URL에서 32자리 16진수가 ID다.

```
https://www.notion.so/내워크스페이스/정리함-3ac2d2f5eb908022adaac7126cebe77d
                                          └────────── 이 부분 ──────────┘
```

- 하이픈이 있어도 없어도 된다.
- `?v=` 뒤에 붙은 것은 **뷰 ID**다. 페이지 ID가 아니다.
- URL에 `?v=` 가 있으면 그건 페이지가 아니라 **데이터베이스**다.
  DB 안에는 DB를 못 만드니, 부모로 쓰려면 일반 페이지가 필요하다.

---

## 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `unauthorized` | 토큰이 틀림 | `.env` 다시 확인. `ntn_` 으로 시작하는지 |
| `object_not_found` | 통합 연결 안 됨 | 4단계 수행 |
| `restricted_resource` | Insert content 권한 꺼짐 | 3단계 확인 |
| search 결과가 비어 있음 | 연결된 페이지가 없음 | 4단계 수행 |
| DB를 못 만듦 | 부모가 DB임 | 일반 페이지를 부모로 |
