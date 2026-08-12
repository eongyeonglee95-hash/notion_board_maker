---
description: 현재 브랜치를 원격 저장소(origin)에 푸시합니다
argument-hint: [브랜치명 (생략하면 현재 브랜치)]
allowed-tools: Bash(git status:*), Bash(git log:*), Bash(git push:*), Bash(git remote:*), Bash(git rev-parse:*), Bash(git branch:*), Bash(git fetch:*), Bash(git diff:*)
---

## 현재 상태

- 브랜치: !`git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "(저장소 아님)"`
- 원격: !`git remote -v 2>/dev/null || echo "(원격 없음)"`
- 푸시 안 된 커밋: !`git log @{u}.. --oneline 2>/dev/null || echo "(업스트림 미설정 — 전체 커밋이 푸시 대상)"`
- 작업 트리: !`git status --short 2>/dev/null`

## 할 일

사용자가 지정한 브랜치: $1

### 1. 푸시할 내용 확인

푸시 안 된 커밋이 없으면 "푸시할 커밋이 없습니다" 라고 알리고 종료한다.

커밋 안 된 변경사항이 남아 있으면 사용자에게 알린다.
푸시는 커밋된 것만 올라가므로, 그것도 올리려면 `/git:commit` 을 먼저 하라고 안내한다.

### 2. 비밀 정보 최종 확인

푸시는 되돌리기 어렵다. 올라갈 커밋들에 토큰이 없는지 확인한다:

```bash
git log @{u}.. -p 2>/dev/null | grep -nE "(ntn_|secret_|sk-[A-Za-z0-9]{20}|ghp_|github_pat_)"
```

업스트림이 없으면 전체 이력을 확인한다:
```bash
git log -p | grep -nE "(ntn_|secret_|sk-[A-Za-z0-9]{20}|ghp_|github_pat_)"
```

**하나라도 걸리면 푸시하지 말고 즉시 중단한다.**
이미 커밋된 토큰은 노션에서 해당 통합의 토큰을 재발급(rotate)해야 하며,
이력에서 제거해야 한다는 것을 알린다.

### 3. 원격 확인

`origin` 이 없으면 사용자에게 알리고 중단한다.

### 4. 푸시

업스트림이 설정되어 있으면:
```bash
git push
```

처음 푸시하는 브랜치면:
```bash
git push -u origin <브랜치명>
```

`--force` 는 **절대 자동으로 쓰지 않는다.** 거절되면 원인을 보고하고 사용자 판단을 받는다.

### 5. 결과 보고

푸시된 커밋 수와 브랜치를 보고한다.
깃허브 저장소 URL 이 있으면 링크를 함께 준다.
