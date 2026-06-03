# 비공개 레포지토리에서 공개 레포지토리로 결과(CSV) 자동 전송 가이드

이 문서는 비공개(Private) 레포지토리에서 수집기 소스코드를 가동하고, 결과물인 CSV 파일만 별도의 공개(Public) 레포지토리로 안전하게 자동 푸시(Push)하는 설정 방법을 설명합니다.

---

## 1. 시스템 아키텍처 및 원리

```mermaid
graph LR
    A[Private 레포지토리<br>소스코드 실행] -->|분석 완료| B(결과 CSV 생성)
    B -->|PAT 토큰 인증| C[Public 레포지토리<br>결과물 전송]
    C -->|누구나 접근 가능| D(상대방이 CSV 다운로드)
```

이 방식을 사용하면 소스코드는 완벽하게 보호하면서 최종 분석 결과 파일만 외부 공유용 공개 저장소에 배포할 수 있습니다.

---

## 2. 설정 절차 3단계

### ① 1단계: 공개 레포지토리 쓰기 권한을 위한 개인 액세스 토큰(PAT) 발급
비공개 레포지토리의 GitHub Actions 러너가 본인의 다른 공개 레포지토리에 커밋 및 푸시를 하려면 쓰기 권한이 필요합니다.

1. GitHub 웹사이트 우측 상단 프로필 이미지 클릭 ➔ **Settings** 선택
2. 좌측 메뉴 맨 아래 **Developer settings** 클릭
3. **Personal access tokens** ➔ **Tokens (classic)** 클릭
4. **Generate new token (classic)** 클릭
5. **Note**란에 용도 기입 (예: `Push-to-Public-Repo`)
6. **Scopes** 선택 항목에서 **`repo`** 전체 권한 체크 (저장소 접근 및 쓰기 권한)
7. 페이지 맨 아래 **Generate token** 클릭
8. 화면에 표시된 토큰 문자열(예: `ghp_...`)을 복사하여 임시 보관합니다. (페이지를 벗어나면 다시 볼 수 없습니다.)

---

### ② 2단계: 비공개(Private) 레포지토리에 보안 비밀변수(Secrets)로 토큰 등록
발급받은 토큰이 외부에 노출되지 않도록 비공개 레포지토리의 환경 변수로 등록합니다.

1. 본인의 **비공개(Private) 레포지토리** 페이지로 이동
2. 상단 메뉴의 **`Settings`** 탭 클릭
3. 좌측 메뉴에서 **`Secrets and variables`** ➔ **`Actions`** 선택
4. **`New repository secret`** 버튼 클릭
5. **Name**에 **`GH_PAT`** 입력
6. **Value**에 1단계에서 복사해 둔 토큰 문자열(`ghp_...`)을 입력하고 **Add secret** 버튼 클릭

---

### ③ 3단계: 워크플로우 설정 파일 (`get_60day_high.yml`) 수정
비공개 레포지토리에 저장된 `.github/workflows/get_60day_high.yml` 파일에서 기존 로컬 푸시 단계를 다른 공개 레포지토리로 푸시하는 아래의 Git 커맨드 스크립트로 대체합니다.

```yaml
    - name: Run Screener Script
      env:
        KRX_ID: ${{ secrets.KRX_ID }}
        KRX_PW: ${{ secrets.KRX_PW }}
      run: |
        python src/get_60day_high.py

    # ★ 변경 적용할 자동 푸시 단계
    - name: Push results to Public Repository
      env:
        API_TOKEN_GITHUB: ${{ secrets.GH_PAT }}
      run: |
        # 1. Git 커밋 작성자 설정
        git config --global user.name "github-actions[bot]"
        git config --global user.email "github-actions[bot]@users.noreply.github.com"
        
        # 2. 발급한 토큰을 이용해 공개 레포지토리를 별도 임시 폴더(public-repo)에 복제(Clone)
        # ※ <내-GitHub-계정명>과 <공개-레포지토리-이름>을 본인의 정보로 변경해 주세요.
        git clone https://x-access-token:${{ secrets.GH_PAT }}@github.com/<내-GitHub-계정명>/<공개-레포지토리-이름>.git public-repo
        
        # 3. 공개 레포지토리 내의 결과물 저장용 경로 생성
        mkdir -p public-repo/result/60day_high
        
        # 4. 방금 분석 가동되어 생성된 결과 CSV 파일들을 공개 레포지토리 폴더로 복사
        cp -r result/60day_high/*.csv public-repo/result/60day_high/
        
        # 5. 공개 레포지토리 폴더 내부로 진입하여 변경사항 커밋 및 푸시
        cd public-repo
        git add result/60day_high/*.csv
        if ! git diff --cached --quiet; then
          git commit -m "Auto-update: 60-day new high results ($(date +'%Y-%m-%d'))"
          git push origin main
        else
          echo "No changes to commit to the public repository."
        fi
```

이 설정을 완료하고 비공개 저장소에 푸시하면, 매일 분석이 끝날 때마다 결과 CSV 파일들이 지정된 공개 레포지토리로 실시간 업데이트 및 배포됩니다.
