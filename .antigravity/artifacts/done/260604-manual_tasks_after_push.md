# Push 후 진행할 수작업 설정 가이드 (Checklist)

이 문서는 로컬 코드를 비공개(Private) 저장소에 푸시한 이후, **GitHub Actions 자동화 및 공개(Public) 저장소 결과 전송**이 정상 동작하도록 하기 위해 GitHub 웹페이지에서 직접 설정해야 하는 필수 수작업 목록입니다.

---

## 1단계: 로컬 코드를 비공개 저장소에 푸시
먼저 로컬에서 작업한 내용을 본인의 비공개 Git 저장소에 업로드합니다.
```bash
git add .
git commit -m "Feat: 분리된 수집기 파이프라인 구축 및 캐시 보완 완료"
git push origin main
```

---

## 2단계: 비공개 저장소 - 쓰기 권한 허용 (필수)
GitHub Actions 가상 컴퓨터가 분석 결과를 다시 저장소에 커밋/푸시할 수 있도록 권한을 설정해야 합니다.

1. 본인의 **비공개(Private) 레포지토리** 페이지 접속
2. 상단 메뉴의 **`Settings`** 탭 클릭
3. 좌측 메뉴의 **`Actions`** ➔ **`General`** 클릭
4. 맨 아래 **`Workflow permissions`** 항목 찾기
5. **`Read and write permissions`** 선택 후 **`Save`** 버튼 클릭

---

## 3단계: 비공개 저장소 - 로그인 자격증명 등록 (권장)
소스코드 노출을 방지하고 보안을 강화하기 위해 KRX 로그인 자격증명을 비밀변수로 등록합니다.

1. **`Settings`** ➔ **`Secrets and variables`** ➔ **`Actions`** 클릭
2. **`New repository secret`** 버튼 클릭
3. 아래 두 개의 변수를 각각 등록합니다.
   * `Name`: **`KRX_ID`** / `Value`: 본인의 KRX 아이디
   * `Name`: **`KRX_PW`** / `Value`: 본인의 KRX 비밀번호

---

## 4단계: 공개 저장소로 결과만 전송하기 위한 설정 (선택 사항)
> **[!] 안내:** 수집기 소스코드는 완전히 숨기고 결과 CSV 파일만 다른 사람들에게 공유(공개 저장소 배포)하고 싶을 때만 이 단계를 진행합니다.

### ① 개인 액세스 토큰 (PAT) 발급
1. GitHub 우측 상단 프로필 이미지 클릭 ➔ **`Settings`** 선택
2. 좌측 메뉴 맨 아래 **`Developer settings`** 클릭
3. **`Personal access tokens`** ➔ **`Tokens (classic)`** 클릭
4. **`Generate new token (classic)`** 클릭
5. **Note**에 용도 기입 (예: `Sync-To-Public-Repo`)
6. **Scopes** 목록에서 **`repo`** (저장소 쓰기 권한) 항목 전체 체크
7. 페이지 하단 **`Generate token`** 클릭 후 생성된 토큰 값(`ghp_...`)을 복사하여 보관

### ② 비공개 저장소에 토큰 등록
1. 본인의 **비공개(Private) 레포지토리** ➔ **`Settings`** ➔ **`Secrets and variables`** ➔ **`Actions`** 이동
2. **`New repository secret`** 클릭
3. `Name`: **`GH_PAT`** / `Value`: 위에서 복사한 토큰 값(`ghp_...`) 입력 후 저장

### ③ 워크플로우 파일 수정
공개 레포지토리로 푸시하려면 `.github/workflows/get_60day_high.yml` 하단의 `Commit and Push changes` 단계 대신, [.antigravity/260604-cross_repo_push_guide.md](file:///d:/dev/work/quant/.antigravity/260604-cross_repo_push_guide.md#L60-L87)에 적힌 스크립트로 대체하여 수정한 뒤 다시 커밋/푸시하시면 됩니다.

---

## 5단계: 자동화 파이프라인 가동 테스트
모든 설정이 완료되면 수동으로 즉시 작동 테스트를 해볼 수 있습니다.

1. 본인의 **비공개(Private) 레포지토리** 상단의 **`Actions`** 탭 클릭
2. 좌측 워크플로우 목록 중 **`Run 60-day New High Screener`** 클릭
3. 우측의 **`Run workflow`** 버튼 클릭 ➔ 브랜치(`main`) 선택 후 실행
4. 약 5~7분 후 성공적으로 완료되면 `result/60day_high/` 경로에 결과가 자동으로 푸시되어 올라옵니다.
