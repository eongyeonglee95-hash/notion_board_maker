---
description: 변경사항을 확인하고 한국어 커밋 메시지로 커밋합니다
argument-hint: [커밋 메시지 (생략하면 변경내용을 보고 자동 작성)]
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git check-ignore:*), Bash(git branch:*)
---

## 현재 상태

- 브랜치: !`git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "(저장소 아님)"`
- 상태: !`git status --short 2>/dev/null || echo "(저장소 아님)"`
- 스테이징된 변경: !`git diff --cached --stat 2>/dev/null`
- 스테이징 안 된 변경: !`git diff --stat 2>/dev/null`
- 최근 커밋: !`git log --oneline -5 2>/dev/null || echo "(커밋 없음)"`

## 할 일

사용자가 준 메시지: $1

### 1. 비밀 정보 차단 (가장 먼저, 건너뛰지 말 것)

커밋에 아래가 포함되면 **즉시 중단**하고 사용자에게 알린다:

- `.env` 파일
- `ntn_` 또는 `secret_` 으로 시작하는 문자열 (노션 토큰)
- `sk-`, `ghp_`, `github_pat_` 로 시작하는 문자열 (API 키, 깃허브 토큰)

확인 방법:
```bash
git status --short | grep -E "^\?\?|^A |^M " | grep -E "\.env$"
git diff --cached | grep -nE "(ntn_|secret_|sk-[A-Za-z0-9]{20}|ghp_|github_pat_)"
```

`.env` 가 목록에 보이면 `.gitignore` 가 제대로 작동하는지 확인한다:
```bash
git check-ignore -v .env
```

### 2. 변경 내용 파악

`git diff` 로 실제로 뭐가 바뀌었는지 읽는다. 파일 이름만 보고 메시지를 쓰지 않는다.

### 3. 스테이징

아직 스테이징 안 된 변경이 있으면, **관련된 파일만** 추가한다.
`git add -A` 는 의도치 않은 파일까지 들어가므로 파일을 지정해서 추가한다.

### 4. 커밋

메시지는 **한국어**로 작성한다. 형식:

```
<타입>: <무엇을 왜 바꿨는지 한 줄>

- 세부 변경 1
- 세부 변경 2
```

타입: `기능` `수정` `문서` `리팩터` `설정` `테스트`

예시:
```
기능: 노션 데이터소스에 행 일괄 추가 기능 구현

- 100개 초과 블록을 나눠서 전송하도록 처리
- 초당 3회 요청 제한에 맞춰 대기 시간 추가
```

사용자가 $1 로 메시지를 줬으면 그것을 제목으로 쓰되, 형식에 맞게 다듬는다.
안 줬으면 diff 를 보고 직접 작성한다.

커밋 메시지 끝에 아래를 붙인다:
```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

### 5. 결과 보고

커밋 해시와 메시지 제목을 한 줄로 보고한다. 푸시는 하지 않는다.
푸시가 필요하면 `/git:push` 를 쓰라고 알려준다.
